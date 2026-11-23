"""รับภาพจากกล้อง (RTSP) หรือไฟล์วิดีโอ

- กล้องหลุด: ต่อใหม่อัตโนมัติ รอ 1, 2, 4 ... สูงสุด max_backoff วินาที
- ลดเฟรมเรตเหลือ target_fps: grab ทุกเฟรม (ให้ buffer ไม่ค้าง) แต่ decode เฉพาะเฟรมที่จะใช้
- เวลา: กล้องสด ใช้นาฬิกาของเครื่อง (UTC) ตอนรับเฟรม ไม่ใช้ timestamp จาก RTSP ซึ่งเชื่อถือไม่ได้
  ไฟล์วิดีโอ ใช้ start_time + ตำแหน่งในไฟล์ (ใช้เล่นซ้ำคลิปเพื่อทดสอบ)

หมายเหตุ: รุ่นนี้ถอดรหัสด้วย OpenCV บน CPU การถอดรหัสบน GPU (NVDEC) ค่อยทำเมื่อวัดแล้วว่า CPU เป็นคอขวด (ROADMAP B6)
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import cv2
import numpy as np

log = logging.getLogger("flock.vision.source")

# RTSP ผ่าน TCP: เสถียรกว่า UDP ในเครือข่ายที่มีแพ็กเก็ตหาย
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000")


@dataclass(frozen=True)
class Frame:
    at: datetime
    image: np.ndarray


def default_opener(url: str) -> Any:
    return cv2.VideoCapture(url, cv2.CAP_FFMPEG)


class VideoSource:
    def __init__(self, url: str, *, target_fps: float = 5.0, live: bool = True, start_time: datetime | None = None,
                 initial_backoff: float = 1.0, max_backoff: float = 30.0,
                 opener: Callable[[str], Any] = default_opener,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.url = url
        self.target_fps = target_fps
        self.live = live
        self.start_time = start_time
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self.opener = opener
        self.clock = clock
        self.connected = False

    def frames(self, stop: threading.Event) -> Iterator[Frame]:
        backoff = self.initial_backoff
        while not stop.is_set():
            cap = self.opener(self.url)
            if not cap.isOpened():
                self.connected = False
                log.warning("cannot open %s, retry in %.0fs", _redact(self.url), backoff)
                if stop.wait(backoff):
                    return
                backoff = min(backoff * 2, self.max_backoff)
                continue
            self.connected = True
            backoff = self.initial_backoff
            start = self.start_time or self.clock()
            yield from self._read(cap, stop, start)
            cap.release()
            self.connected = False
            if not self.live:
                return  # ไฟล์จบแล้ว
            log.warning("stream %s ended, reconnecting", _redact(self.url))

    def _read(self, cap: Any, stop: threading.Event, start: datetime) -> Iterator[Frame]:
        interval = 1.0 / self.target_fps
        next_at: float | None = None
        while not stop.is_set():
            if not cap.grab():
                return
            if self.live:
                at = self.clock()
            else:
                at = start + timedelta(milliseconds=cap.get(cv2.CAP_PROP_POS_MSEC))
            t = at.timestamp()
            if next_at is not None and t < next_at:
                continue
            ok, image = cap.retrieve()
            if not ok:
                return
            # เผื่อ 5% ให้ jitter ของเวลาเฟรม ไม่อย่างนั้นอาจข้ามไปอีกหนึ่งเฟรมเป็นระยะ
            next_at = t + interval * 0.95
            yield Frame(at, image)


def _redact(url: str) -> str:
    """ไม่เขียนรหัสผ่านกล้องลง log"""
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        return f"{scheme}://***@{rest.split('@', 1)[1]}"
    return url
