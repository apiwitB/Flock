"""ประมวลผลภาพของกล้องหนึ่งตัว: ตรวจจับ → ติดตาม → อ่านป้าย → เลือกภาพดีที่สุด → บันทึกภาพ → ส่ง event"""

from __future__ import annotations

import logging
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from flock_contracts import SightingEvent
from flock_vision.bestshot import BestShotSelector, PlateReading, TrackRecord
from flock_vision.detectors import Detector
from flock_vision.geometry import Box, Detection
from flock_vision.readers import PlateRecognizer
from flock_vision.sink import ImageStore
from flock_vision.tracker import Tracker

log = logging.getLogger("flock.vision.pipeline")


@dataclass(frozen=True)
class PipelineConfig:
    plate_min_score: float = 0.4
    plate_min_width: float = 40.0  # ป้ายเล็กกว่านี้ (พิกเซล) อ่านไม่ออกอยู่แล้ว ไม่เสียเวลา OCR
    plate_pad: float = 0.08


class CameraPipeline:
    def __init__(self, camera_id: str, *, vehicle_detector: Detector, plate_detector: Detector | None,
                 plate_reader: PlateRecognizer | None, store: ImageStore,
                 publish: Callable[[SightingEvent], None], tracker: Tracker | None = None,
                 selector: BestShotSelector | None = None, config: PipelineConfig | None = None,
                 run_id: str | None = None, max_pending: int = 10_000):
        self.camera_id = camera_id
        self.vehicle_detector = vehicle_detector
        self.plate_detector = plate_detector
        self.plate_reader = plate_reader
        self.store = store
        self.publish = publish
        self.tracker = tracker or Tracker()
        self.selector = selector or BestShotSelector()
        self.cfg = config or PipelineConfig()
        # track_id ของ tracker เริ่มนับใหม่ทุกครั้งที่ process เริ่ม: ใส่ run_id กัน id ชนกันข้ามรอบ
        self.run_id = run_id or uuid.uuid4().hex[:8]
        # event ที่ส่งไม่สำเร็จ รอส่งซ้ำ จำกัดจำนวนกันหน่วยความจำเต็มถ้าคิวล่มนาน (เกินแล้วทิ้งตัวเก่าสุด)
        self._pending: deque[SightingEvent] = deque(maxlen=max_pending)
        self.reader_versions = {"vehicle_det": vehicle_detector.version}
        if plate_detector is not None:
            self.reader_versions["plate_det"] = plate_detector.version
        if plate_reader is not None:
            self.reader_versions["plate"] = plate_reader.version

    def process(self, at: datetime, frame: np.ndarray) -> list[SightingEvent]:
        vehicles = self.vehicle_detector.detect(frame)
        seen, ended = self.tracker.update(vehicles, at)
        plates = self._plates(frame) if seen else []
        for track in seen:
            if track.last_seen != at:
                continue
            plate_box, reading = self._read_plate(frame, track.box, plates)
            self.selector.observe(track.track_id, at, frame, track.box, plate_box, reading,
                                  label=track.label, label_score=track.score)
        return self._emit(at, {t.track_id for t in ended})

    def close(self, at: datetime) -> list[SightingEvent]:
        """ปิดกล้อง: ส่ง event ของทุก track ที่ยังค้างอยู่"""
        ended = self.tracker.flush()
        return self._emit(at, {t.track_id for t in ended})

    def _plates(self, frame: np.ndarray) -> list[Detection]:
        if self.plate_detector is None:
            return []
        return [d for d in self.plate_detector.detect(frame) if d.score >= self.cfg.plate_min_score]

    def _read_plate(self, frame: np.ndarray, vehicle: Box,
                    plates: list[Detection]) -> tuple[Box | None, PlateReading | None]:
        inside = [p for p in plates if vehicle.contains_point(*p.box.center)]
        if not inside:
            return None, None
        plate = max(inside, key=lambda p: p.score).box
        if self.plate_reader is None or plate.width < self.cfg.plate_min_width:
            return plate, None
        crop = plate.padded(self.cfg.plate_pad).crop(frame)
        if crop.size == 0:
            return plate, None
        return plate, self.plate_reader.read(crop)

    def _emit(self, now: datetime, ended_ids: set[int]) -> list[SightingEvent]:
        """คืน event ที่ส่งเข้าคิวสำเร็จในรอบนี้ (รวมที่ค้างจากรอบก่อน)"""
        for rec in self.selector.due(now, ended_ids):
            try:
                self._pending.append(self._event(rec))
            except Exception:
                # event หนึ่งพังต้องไม่ทำให้ทั้งกล้องหยุด (เช่น ดิสก์เต็มชั่วคราว)
                log.exception("camera %s: failed to build event for track %d", self.camera_id, rec.track_id)
        sent = []
        while self._pending:
            try:
                self.publish(self._pending[0])
            except Exception as e:
                # คิวล่มชั่วคราว: เก็บไว้ส่งรอบหน้า (ภาพบันทึกไว้แล้ว) ไม่ทิ้ง event
                # log สั้นๆ ไม่มี traceback เพราะจะเกิดซ้ำทุกเฟรมจนกว่าคิวจะกลับมา
                log.warning("camera %s: queue unavailable (%s), %d events pending",
                            self.camera_id, type(e).__name__, len(self._pending))
                break
            sent.append(self._pending.popleft())
        return sent

    def _event(self, rec: TrackRecord) -> SightingEvent:
        shot = rec.best
        assert shot is not None
        sid = uuid.uuid4()
        crop_path, context_path = self.store.save(sid, self.camera_id, shot.at, shot.vehicle_crop, shot.context)
        plate = rec.plate_vote()
        prov = rec.province_vote() if plate else None
        attributes = {}
        if rec.label:
            # ประเภทรถจาก detector (car/truck/bus/motorcycle) ความมั่นใจคือคะแนนของ detector ในเฟรมล่าสุด
            attributes["vehicle_type"] = {"value": rec.label, "confidence": round(rec.label_score, 4)}
        return SightingEvent.model_validate({
            "sighting_id": sid,
            "camera_id": self.camera_id,
            "observed_at": shot.at,
            "subject_type": "vehicle",
            "track_id": f"{self.camera_id}.{self.run_id}.{rec.track_id}"[-64:],
            "plate": {"text": plate.value, "confidence": plate.confidence,
                      "province": prov.value if prov else None,
                      "province_confidence": prov.confidence if prov else None} if plate else None,
            "attributes": attributes,
            "embedding": None,
            "embedding_model": None,
            "images": {"crop_path": crop_path, "context_path": context_path},
            "reader_versions": self.reader_versions,
        })
