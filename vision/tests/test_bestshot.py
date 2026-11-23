from datetime import UTC, datetime, timedelta

import cv2
import numpy as np
import pytest

from flock_vision.bestshot import BestShotConfig, BestShotSelector, PlateReading, sharpness, vote
from flock_vision.geometry import Box

T0 = datetime(2026, 11, 23, 1, 0, tzinfo=UTC)
CAR = Box(100, 100, 400, 300)
PLATE = Box(200, 240, 300, 270)


def frame(blur: int = 0) -> np.ndarray:
    rng = np.random.default_rng(0)
    f = rng.integers(0, 255, (480, 640, 3), dtype=np.uint8)
    return cv2.GaussianBlur(f, (blur * 2 + 1, blur * 2 + 1), 0) if blur else f


def test_vote_majority_beats_single_confident_misread():
    v = vote([("1กข1234", 0.8), ("1กข1234", 0.7), ("1กข1234", 0.75), ("1กช1234", 0.95)])
    assert v.value == "1กข1234" and v.support == 3 and v.total == 4
    # สัดส่วน 2.25/3.2 × เฉลี่ย 0.75
    assert v.confidence == pytest.approx((2.25 / 3.2) * 0.75, abs=1e-4)


def test_vote_disagreement_lowers_confidence():
    agree = vote([("กข1", 0.9)] * 4)
    split = vote([("กข1", 0.9), ("กข1", 0.9), ("กช1", 0.9), ("กง1", 0.9)])
    assert agree.confidence == pytest.approx(0.9)
    assert split.confidence < 0.5


def test_vote_ignores_empty():
    assert vote([]) is None
    assert vote([("", 0.9), ("x", 0.0)]) is None


def test_sharpness_prefers_sharp():
    assert sharpness(frame()) > sharpness(frame(blur=3)) * 5


def test_emits_once_when_track_ends_with_best_frame_and_vote():
    sel = BestShotSelector(BestShotConfig(min_hits=3, emit_after_seconds=60))
    readings = [("1กข1234", 0.6), ("1กข1234", 0.9), ("1กช1234", 0.5)]
    for i, (text, conf) in enumerate(readings):
        sel.observe(7, T0 + timedelta(seconds=i), frame(blur=0 if i == 1 else 3), CAR, PLATE,
                    PlateReading(text, conf, "กรุงเทพมหานคร", 0.8))
    assert sel.due(T0 + timedelta(seconds=3), set()) == []
    (rec,) = sel.due(T0 + timedelta(seconds=4), {7})
    assert rec.best.at == T0 + timedelta(seconds=1)  # เฟรมที่คมและมั่นใจที่สุด
    assert rec.plate_vote().value == "1กข1234"
    assert rec.province_vote().value == "กรุงเทพมหานคร"
    assert rec.best.vehicle_crop.shape == (200, 300, 3)
    assert 7 not in sel.records


def test_parked_car_emits_once_and_releases_images():
    sel = BestShotSelector(BestShotConfig(min_hits=2, emit_after_seconds=5))
    for i in range(10):
        sel.observe(1, T0 + timedelta(seconds=i), frame(), CAR, None, None)
        emitted = sel.due(T0 + timedelta(seconds=i), set())
        assert len(emitted) == (1 if i == 5 else 0)
    assert sel.records[1].best is None  # ไม่ถือภาพไว้ระหว่างรถจอดนิ่ง
    assert sel.due(T0 + timedelta(seconds=20), {1}) == []  # จบแล้วก็ไม่ส่งซ้ำ


def test_short_noise_track_is_dropped():
    sel = BestShotSelector(BestShotConfig(min_hits=3))
    sel.observe(1, T0, frame(), CAR, None, None)
    assert sel.due(T0 + timedelta(seconds=3), {1}) == []
    assert not sel.records


def test_frame_with_plate_beats_bigger_frame_without():
    sel = BestShotSelector(BestShotConfig(min_hits=1, emit_after_seconds=60))
    sel.observe(1, T0, frame(), Box(0, 0, 640, 480), None, None)
    sel.observe(1, T0 + timedelta(seconds=1), frame(blur=3), CAR, PLATE, PlateReading("กข1", 0.4))
    (rec,) = sel.due(T0 + timedelta(seconds=2), {1})
    assert rec.best.at == T0 + timedelta(seconds=1)


def test_context_is_downscaled():
    sel = BestShotSelector(BestShotConfig(min_hits=1, context_max_width=320))
    sel.observe(1, T0, frame(), CAR, None, None)
    assert sel.records[1].best.context.shape == (240, 320, 3)
