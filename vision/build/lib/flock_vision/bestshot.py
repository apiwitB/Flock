"""รวมผลหลายเฟรมของ track เดียว ให้เหลือ 1 sighting

- ป้าย: โหวตถ่วงน้ำหนักด้วยความมั่นใจของ OCR จากทุกเฟรม (OCR ผิดบางเฟรมไม่ทำให้ผลผิด)
- ความมั่นใจที่รายงาน = สัดส่วนน้ำหนักของผู้ชนะ × ความมั่นใจเฉลี่ยของผู้ชนะ
  ถ้าเฟรมต่างๆ อ่านได้ไม่ตรงกัน ความมั่นใจจะต่ำลงเอง (ไม่รายงานว่ามั่นใจทั้งที่ผลขัดกัน)
- ภาพ: เก็บเฉพาะเฟรมที่ดีที่สุด (ป้ายใหญ่ คม OCR มั่นใจ) เพื่อจำกัดหน่วยความจำ
- ส่ง event ครั้งเดียวต่อ track: เมื่อ track จบ หรือเมื่อเห็นมานานพอ (รถจอดนิ่งในภาพจะไม่ส่งซ้ำ)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

import cv2
import numpy as np

from flock_vision.geometry import Box


@dataclass(frozen=True)
class PlateReading:
    text: str
    confidence: float
    province: str | None = None
    province_confidence: float | None = None


@dataclass(frozen=True)
class Vote:
    value: str
    confidence: float
    support: int  # จำนวนเฟรมที่อ่านได้ค่านี้
    total: int  # จำนวนเฟรมที่อ่านได้ทั้งหมด


def vote(readings: list[tuple[str, float]]) -> Vote | None:
    weights: dict[str, list[float]] = defaultdict(list)
    for value, conf in readings:
        if value and conf > 0:
            weights[value].append(conf)
    if not weights:
        return None
    total_w = sum(sum(v) for v in weights.values())
    winner, confs = max(weights.items(), key=lambda kv: (sum(kv[1]), len(kv[1])))
    confidence = (sum(confs) / total_w) * (sum(confs) / len(confs))
    return Vote(winner, round(confidence, 4), len(confs), sum(len(v) for v in weights.values()))


def sharpness(img: np.ndarray) -> float:
    """ความคมของภาพ (variance ของ Laplacian) ใช้เทียบเฟรมในกล้องเดียวกัน"""
    if img.size == 0:
        return 0.0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


@dataclass
class Shot:
    score: float
    at: datetime
    vehicle_crop: np.ndarray
    context: np.ndarray
    vehicle_box: Box


@dataclass
class TrackRecord:
    track_id: int
    first_seen: datetime
    hits: int = 0
    plates: list[PlateReading] = field(default_factory=list)
    best: Shot | None = None
    emitted: bool = False
    label: str | None = None  # ประเภทรถส่วนใหญ่ของ track (จาก detector)
    label_score: float = 0.0

    def plate_vote(self) -> Vote | None:
        return vote([(p.text, p.confidence) for p in self.plates])

    def province_vote(self) -> Vote | None:
        return vote([(p.province, p.province_confidence or 0.0) for p in self.plates if p.province])


@dataclass(frozen=True)
class BestShotConfig:
    min_hits: int = 3  # track สั้นกว่านี้ถือว่าเป็นสัญญาณรบกวน
    emit_after_seconds: float = 8.0  # ส่งเมื่อเห็นมานานเท่านี้ แม้ track ยังไม่จบ
    context_max_width: int = 960  # ย่อภาพมุมกว้างก่อนเก็บ


class BestShotSelector:
    def __init__(self, config: BestShotConfig | None = None):
        self.cfg = config or BestShotConfig()
        self.records: dict[int, TrackRecord] = {}

    def observe(self, track_id: int, at: datetime, frame: np.ndarray, vehicle_box: Box,
                plate_box: Box | None, plate: PlateReading | None, *, label: str | None = None,
                label_score: float = 0.0) -> None:
        rec = self.records.setdefault(track_id, TrackRecord(track_id, at))
        rec.hits += 1
        if label is not None:
            rec.label, rec.label_score = label, label_score
        if plate is not None:
            rec.plates.append(plate)

        crop = vehicle_box.crop(frame)
        if crop.size == 0:
            return
        if plate_box is not None and plate is not None:
            # มีป้าย: ให้คะแนนตามความกว้างป้าย × ความคม × ความมั่นใจ OCR และชนะเฟรมที่ไม่มีป้ายเสมอ
            score = 1e6 + plate_box.width * np.log1p(sharpness(plate_box.crop(frame))) * plate.confidence
        else:
            score = vehicle_box.area * np.log1p(sharpness(crop)) / 1e3
        if rec.best is None or score > rec.best.score:
            rec.best = Shot(score, at, crop.copy(), self._context(frame), vehicle_box)

    def due(self, now: datetime, ended_ids: set[int]) -> list[TrackRecord]:
        """record ที่ถึงเวลาส่ง; record ของ track ที่จบแล้วถูกลบออก"""
        out = []
        for tid in list(self.records):
            rec = self.records[tid]
            ended = tid in ended_ids
            long_enough = (now - rec.first_seen).total_seconds() >= self.cfg.emit_after_seconds
            if not rec.emitted and rec.hits >= self.cfg.min_hits and rec.best is not None and (ended or long_enough):
                rec.emitted = True
                out.append(rec)
            if ended:
                del self.records[tid]
            elif rec.emitted:
                # ส่งแล้ว: ไม่ต้องเก็บภาพต่อ (รถจอดนิ่งในภาพอาจอยู่เป็นชั่วโมง)
                rec.best, rec.plates = None, []
        return out

    def _context(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        if w <= self.cfg.context_max_width:
            return frame.copy()
        scale = self.cfg.context_max_width / w
        return cv2.resize(frame, (self.cfg.context_max_width, int(h * scale)), interpolation=cv2.INTER_AREA)
