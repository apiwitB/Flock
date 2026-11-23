"""รัน vision worker ตามไฟล์ตั้งค่า

    flock-vision --config /etc/flock/vision.toml

หนึ่ง process รันได้หลายกล้อง (thread ละกล้อง) โมเดลโหลดครั้งเดียวแล้วใช้ร่วมกัน
การรวม batch ข้ามกล้องเพื่อใช้ GPU คุ้มขึ้นยังไม่ได้ทำ (ROADMAP B6)
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import threading
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import redis

from flock_vision.bestshot import BestShotConfig, BestShotSelector
from flock_vision.detectors import COCO_VEHICLES, Detector, HFDetector
from flock_vision.geometry import Detection
from flock_vision.pipeline import CameraPipeline, PipelineConfig
from flock_vision.readers import OnnxPlateReader
from flock_vision.sink import ImageStore, QueuePublisher
from flock_vision.source import VideoSource
from flock_vision.tracker import Tracker, TrackerConfig

log = logging.getLogger("flock.vision")


class LockedDetector:
    """ให้หลายกล้องใช้โมเดลเดียวกันได้อย่างปลอดภัย"""

    def __init__(self, inner: Detector):
        self.inner = inner
        self.version = inner.version
        self._lock = threading.Lock()

    def detect(self, frame: np.ndarray) -> list[Detection]:
        with self._lock:
            return self.inner.detect(frame)


def camera_url(cam: dict[str, Any]) -> str:
    """URL ของกล้องมักมีรหัสผ่าน จึงให้อ่านจาก environment (url_env) แทนการเขียนในไฟล์"""
    if "url_env" in cam:
        url = os.environ.get(cam["url_env"])
        if not url:
            raise SystemExit(f"camera {cam['id']}: environment variable {cam['url_env']} is not set")
        return url
    return cam["url"]


def run_camera(cam: dict[str, Any], pipeline: CameraPipeline, stop: threading.Event) -> None:
    source = VideoSource(camera_url(cam), target_fps=float(cam.get("fps", 5)), live=cam.get("live", True))
    frames = events = 0
    for frame in source.frames(stop):
        try:
            events += len(pipeline.process(frame.at, frame.image))
        except Exception:
            log.exception("camera %s: frame failed", cam["id"])
        frames += 1
        if frames % 1000 == 0:
            log.info("camera %s: %d frames, %d events", cam["id"], frames, events)
    events += len(pipeline.close(datetime.now(UTC)))
    log.info("camera %s stopped: %d frames, %d events", cam["id"], frames, events)


def build(config: dict[str, Any]) -> list[tuple[dict[str, Any], CameraPipeline]]:
    models = config.get("models", {})
    vehicle = LockedDetector(HFDetector(models.get("vehicle_detector", "PekingU/rtdetr_v2_r18vd"), keep=COCO_VEHICLES))
    plate_det = LockedDetector(HFDetector(models["plate_detector"])) if models.get("plate_detector") else None
    reader = (OnnxPlateReader(models["plate_ocr"], models.get("province"), text_split=models.get("text_split", 0.62),
                              version=Path(models["plate_ocr"]).stem)
              if models.get("plate_ocr") else None)
    if plate_det is None or reader is None:
        log.warning("plate detector or OCR not configured: events will have no plate")

    client = redis.Redis.from_url(os.environ[config.get("queue_url_env", "FLOCK_QUEUE_URL")])
    store = ImageStore(Path(config.get("image_root", "/data/images")))
    publish = QueuePublisher(client)
    out = []
    for cam in config["cameras"]:
        out.append((cam, CameraPipeline(
            cam["id"], vehicle_detector=vehicle, plate_detector=plate_det, plate_reader=reader, store=store,
            publish=publish, tracker=Tracker(TrackerConfig(**config.get("tracker", {}))),
            selector=BestShotSelector(BestShotConfig(**config.get("bestshot", {}))),
            config=PipelineConfig(**config.get("pipeline", {})),
        )))
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, default=Path("/etc/flock/vision.toml"))
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    config = tomllib.loads(a.config.read_text(encoding="utf-8"))
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    threads = [threading.Thread(target=run_camera, args=(cam, pipe, stop), name=cam["id"], daemon=True)
               for cam, pipe in build(config)]
    for t in threads:
        t.start()
    log.info("vision worker running %d cameras", len(threads))
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
