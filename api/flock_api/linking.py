"""กฎการต่อ sighting เข้ากับ journey (ไม่แตะฐานข้อมูล ทดสอบได้ตรงๆ)

ลำดับความน่าเชื่อถือ (README ข้อ 5):
  1. exact          ป้ายตรงกันทุกตัว และเวลาเดินทางเป็นไปได้ตามผังอาคาร
  2. similar_plate  ป้ายต่างกันไม่เกิน similar_max_distance, สี/ประเภทไม่ขัดกัน, เวลาเป็นไปได้
  3. guess          ใช้ embedding เมื่อไม่มีป้ายให้เทียบ: ต้องเป็นกล้องที่ติดกัน ในช่วงเวลาที่สมเหตุสมผล
                    คล้ายเกินเกณฑ์ และต้องชนะคันที่คล้ายรองลงมาอย่างชัดเจน
  4. new            ไม่เข้าเงื่อนไขใดเลย → เปิด journey ใหม่

หลักการ: ถ้าไม่แน่ใจให้เปิด journey ใหม่ ดีกว่าต่อผิด (ระบบต้องไม่ "แน่ใจ" ทั้งที่เดา)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from flock_api.topology import Topology
from flock_contracts import plate_distance

# ความคลาดเคลื่อนของนาฬิกาข้ามกล้องที่ยอมรับได้
CLOCK_TOLERANCE_S = 2.0


@dataclass(frozen=True)
class Observation:
    camera_id: str
    observed_at: datetime
    plate_text: str | None
    color: str | None
    vehicle_type: str | None


@dataclass(frozen=True)
class Candidate:
    journey_id: int
    plate_text: str | None
    last_camera_id: str
    last_seen: datetime  # sighting ล่าสุดของ journey ที่เกิดก่อน observation
    color: str | None
    vehicle_type: str | None
    similarity: float | None  # cosine similarity ของ embedding (None ถ้าฝั่งใดไม่มี)


@dataclass(frozen=True)
class Decision:
    journey_id: int | None  # None = เปิด journey ใหม่
    method: str
    score: float | None
    reason: str


def _consistent(o: Observation, c: Candidate) -> bool:
    """สี/ประเภทไม่ขัดกัน (ถ้าฝั่งใดไม่รู้ ถือว่าไม่ขัด)"""
    return all(a is None or b is None or a == b for a, b in ((o.color, c.color), (o.vehicle_type, c.vehicle_type)))


def _reachable(o: Observation, c: Candidate, topo: Topology) -> bool:
    """เดินทางจากกล้องล่าสุดของ journey มาถึงกล้องนี้ทันหรือไม่ (ใช้กับ exact/similar)"""
    dt = (o.observed_at - c.last_seen).total_seconds()
    if dt < -CLOCK_TOLERANCE_S:
        return False
    if not (topo.knows(o.camera_id) and topo.knows(c.last_camera_id)):
        return True  # กล้องที่ยังไม่อยู่ในผัง: ตรวจเวลาไม่ได้ จึงไม่ใช้เป็นเหตุตัดทิ้ง
    fastest = topo.fastest(c.last_camera_id, o.camera_id)
    return fastest is not None and dt + CLOCK_TOLERANCE_S >= fastest


def _adjacent_in_window(o: Observation, c: Candidate, topo: Topology) -> bool:
    """สำหรับการเดา: ต้องเป็นกล้องติดกัน และใช้เวลาในช่วงของการวิ่งโดยไม่หยุดจอด"""
    dt = (o.observed_at - c.last_seen).total_seconds()
    if dt < -CLOCK_TOLERANCE_S:
        return False
    if o.camera_id == c.last_camera_id:
        return dt <= topo.config.same_camera_gap_seconds
    edge = topo.direct(c.last_camera_id, o.camera_id)
    return edge is not None and edge.min_seconds - CLOCK_TOLERANCE_S <= dt <= edge.max_seconds + CLOCK_TOLERANCE_S


def decide(o: Observation, candidates: list[Candidate], topo: Topology) -> Decision:
    cfg = topo.config

    if o.plate_text:
        exact = [c for c in candidates if c.plate_text == o.plate_text and _reachable(o, c, topo)]
        if exact:
            best = max(exact, key=lambda c: c.last_seen)
            return Decision(best.journey_id, "exact", 1.0, "plate matches exactly")

        scored = []
        for c in candidates:
            if c.plate_text and _consistent(o, c) and _reachable(o, c, topo):
                d = plate_distance(o.plate_text, c.plate_text)
                if d <= cfg.similar_max_distance:
                    scored.append((d, c))
        if scored:
            scored.sort(key=lambda x: x[0])
            if len(scored) > 1 and scored[1][0] == scored[0][0]:
                return Decision(None, "new", None, "several journeys have an equally similar plate")
            d, best = scored[0]
            score = round(1.0 - d / (cfg.similar_max_distance + 1.0), 3)
            return Decision(best.journey_id, "similar_plate", score, f"plate distance {d:g}")

    # เดา: ห้ามต่อกับ journey ที่มีป้ายอื่นที่ขัดกับป้ายของ observation
    guesses = sorted(
        (
            (c.similarity, c)
            for c in candidates
            if c.similarity is not None
            and not (o.plate_text and c.plate_text)
            and _consistent(o, c)
            and _adjacent_in_window(o, c, topo)
        ),
        key=lambda x: -x[0],
    )
    if guesses:
        sim, best = guesses[0]
        if sim < cfg.guess_min_similarity:
            return Decision(None, "new", None, f"best embedding similarity {sim:.3f} below threshold")
        if len(guesses) > 1 and sim - guesses[1][0] < cfg.guess_margin:
            return Decision(None, "new", None, "ambiguous: two journeys look alike")
        return Decision(best.journey_id, "guess", round(sim, 3), f"embedding similarity {sim:.3f}")

    return Decision(None, "new", None, "no matching journey")
