from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Box:
    """กรอบในพิกัดพิกเซลของภาพเต็ม (x1, y1) มุมซ้ายบน (x2, y2) มุมขวาล่าง"""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2

    def shifted(self, dx: float, dy: float) -> Box:
        return Box(self.x1 + dx, self.y1 + dy, self.x2 + dx, self.y2 + dy)

    def contains_point(self, x: float, y: float) -> bool:
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2

    def padded(self, frac: float) -> Box:
        px, py = self.width * frac, self.height * frac
        return Box(self.x1 - px, self.y1 - py, self.x2 + px, self.y2 + py)

    def crop(self, frame: np.ndarray) -> np.ndarray:
        """ตัดภาพ (ตัดส่วนที่เกินขอบภาพทิ้ง) คืน array ว่างถ้าไม่เหลือพื้นที่"""
        h, w = frame.shape[:2]
        x1, y1 = max(0, int(self.x1)), max(0, int(self.y1))
        x2, y2 = min(w, int(round(self.x2))), min(h, int(round(self.y2)))
        if x2 <= x1 or y2 <= y1:
            return frame[0:0, 0:0]
        return frame[y1:y2, x1:x2]


def iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = ix * iy
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


@dataclass(frozen=True)
class Detection:
    box: Box
    label: str
    score: float
