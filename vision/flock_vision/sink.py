"""บันทึกภาพและส่ง event

ลำดับสำคัญ: เขียนภาพให้เสร็จก่อนส่ง event เสมอ ไม่อย่างนั้นหน้าเว็บอาจเปิดภาพที่ยังไม่มี
โครงสร้างโฟลเดอร์: {root}/{YYYY-MM-DD (UTC)}/{camera_id}/{sighting_id}_{crop|context}.jpg
ใช้วันที่ UTC ให้ตรงกับ partition รายวันของฐานข้อมูล งานลบตามรอบจึงลบทั้งโฟลเดอร์ของวันนั้นได้
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import cv2
import numpy as np

from flock_contracts import SightingEvent
from flock_contracts.stream import publish

JPEG_QUALITY = 90


class ImageStore:
    def __init__(self, root: Path):
        self.root = root

    def save(self, sighting_id: UUID, camera_id: str, at: datetime, crop: np.ndarray,
             context: np.ndarray) -> tuple[str, str]:
        rel_dir = Path(at.strftime("%Y-%m-%d")) / camera_id
        (self.root / rel_dir).mkdir(parents=True, exist_ok=True)
        paths = []
        for kind, img in (("crop", crop), ("context", context)):
            rel = rel_dir / f"{sighting_id}_{kind}.jpg"
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if not ok:
                raise RuntimeError(f"cannot encode {kind} image")
            tmp = self.root / rel.with_suffix(".tmp")
            tmp.write_bytes(buf.tobytes())
            os.replace(tmp, self.root / rel)  # ผู้อ่านจะไม่เห็นไฟล์ที่เขียนไม่ครบ
            paths.append(rel.as_posix())
        return paths[0], paths[1]


class QueuePublisher:
    def __init__(self, client: Any):
        self.client = client

    def __call__(self, event: SightingEvent) -> None:
        publish(self.client, event)
