"""ติดตามรถภายในกล้องเดียว แบบ ByteTrack อย่างง่าย

- จับคู่ 2 รอบ: รอบแรกใช้กรอบที่มั่นใจสูง รอบสองใช้กรอบที่มั่นใจต่ำ (เช่น รถถูกบังบางส่วน)
  กับ track ที่ยังไม่ได้คู่ ซึ่งช่วยไม่ให้ track ขาดตอนเมื่อ detector ลังเล
- ทำนายตำแหน่งด้วยความเร็วคงที่ ก่อนเทียบ IoU (รถในอาคารวิ่งช้าและตรง)
- track ที่หายไปนานเกิน max_lost_seconds ถือว่าจบ

ไม่มี Kalman filter: ที่ 5-10 fps ในอาคารจอดรถ การทำนายแบบเส้นตรงพอ ถ้าวัดแล้วไม่พอค่อยเปลี่ยน
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from flock_vision.geometry import Box, Detection, iou


@dataclass
class Track:
    track_id: int
    box: Box
    first_seen: datetime
    last_seen: datetime
    score: float
    hits: int = 1
    vx: float = 0.0  # พิกเซลต่อวินาที
    vy: float = 0.0
    labels: Counter = field(default_factory=Counter)

    @property
    def label(self) -> str:
        return self.labels.most_common(1)[0][0]

    def predicted(self, at: datetime) -> Box:
        dt = (at - self.last_seen).total_seconds()
        return self.box.shifted(self.vx * dt, self.vy * dt)


@dataclass(frozen=True)
class TrackerConfig:
    high_score: float = 0.5
    low_score: float = 0.1
    match_iou: float = 0.3
    low_match_iou: float = 0.5
    max_lost_seconds: float = 2.0
    velocity_smoothing: float = 0.5


class Tracker:
    def __init__(self, config: TrackerConfig | None = None):
        self.cfg = config or TrackerConfig()
        self.tracks: dict[int, Track] = {}
        self._next_id = 1

    def update(self, detections: list[Detection], at: datetime) -> tuple[list[Track], list[Track]]:
        """คืน (track ที่เห็นในเฟรมนี้, track ที่จบแล้ว)"""
        high = [d for d in detections if d.score >= self.cfg.high_score]
        low = [d for d in detections if self.cfg.low_score <= d.score < self.cfg.high_score]
        predicted = {tid: t.predicted(at) for tid, t in self.tracks.items()}

        matched: dict[int, Detection] = {}
        unmatched_high = self._match(high, predicted, self.cfg.match_iou, matched)
        self._match(low, {k: v for k, v in predicted.items() if k not in matched}, self.cfg.low_match_iou, matched)

        seen = []
        for tid, det in matched.items():
            seen.append(self._apply(self.tracks[tid], det, at))
        for det in unmatched_high:
            t = Track(self._next_id, det.box, at, at, det.score, labels=Counter({det.label: 1}))
            self.tracks[t.track_id] = t
            self._next_id += 1
            seen.append(t)

        ended = [t for t in self.tracks.values()
                 if t.track_id not in matched and (at - t.last_seen).total_seconds() > self.cfg.max_lost_seconds]
        for t in ended:
            del self.tracks[t.track_id]
        return seen, ended

    def flush(self) -> list[Track]:
        """จบทุก track (เช่น ตอนปิดกล้อง)"""
        ended = list(self.tracks.values())
        self.tracks.clear()
        return ended

    @staticmethod
    def _match(dets: list[Detection], boxes: dict[int, Box], min_iou: float,
               matched: dict[int, Detection]) -> list[Detection]:
        """จับคู่แบบ greedy ตาม IoU มากไปน้อย คืน detection ที่ไม่ได้คู่"""
        pairs = sorted(((iou(b, d.box), tid, i) for tid, b in boxes.items() for i, d in enumerate(dets)),
                       reverse=True)
        used = set()
        for score, tid, i in pairs:
            if score < min_iou:
                break
            if tid in matched or i in used:
                continue
            matched[tid] = dets[i]
            used.add(i)
        return [d for i, d in enumerate(dets) if i not in used]

    def _apply(self, t: Track, det: Detection, at: datetime) -> Track:
        dt = (at - t.last_seen).total_seconds()
        if dt > 0:
            (ox, oy), (nx, ny) = t.box.center, det.box.center
            a = self.cfg.velocity_smoothing
            t.vx = a * (nx - ox) / dt + (1 - a) * t.vx
            t.vy = a * (ny - oy) / dt + (1 - a) * t.vy
        t.box, t.last_seen, t.score = det.box, at, det.score
        t.hits += 1
        t.labels[det.label] += 1
        return t
