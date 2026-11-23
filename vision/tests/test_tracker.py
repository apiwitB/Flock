from datetime import UTC, datetime, timedelta

from flock_vision.geometry import Box, Detection, iou
from flock_vision.tracker import Tracker

T0 = datetime(2026, 11, 23, 1, 0, tzinfo=UTC)


def at(i: int, fps: float = 5) -> datetime:
    return T0 + timedelta(seconds=i / fps)


def car(x: float, y: float = 100, score: float = 0.9, w: float = 200, h: float = 120) -> Detection:
    return Detection(Box(x, y, x + w, y + h), "car", score)


def test_iou():
    a = Box(0, 0, 10, 10)
    assert iou(a, a) == 1
    assert iou(a, Box(5, 0, 15, 10)) == 50 / 150
    assert iou(a, Box(20, 20, 30, 30)) == 0


def test_single_car_keeps_one_id_while_moving():
    tr = Tracker()
    ids = set()
    for i in range(20):
        seen, ended = tr.update([car(100 + 30 * i)], at(i))
        ids |= {t.track_id for t in seen}
        assert not ended
    assert ids == {1}
    t = tr.tracks[1]
    assert t.hits == 20
    assert 140 < t.vx < 160  # 30 px ต่อเฟรม ที่ 5 fps


def test_two_cars_get_separate_ids():
    tr = Tracker()
    for i in range(10):
        seen, _ = tr.update([car(100 + 20 * i, y=50), car(900 - 20 * i, y=400)], at(i))
    assert sorted(t.track_id for t in seen) == [1, 2]


def test_short_occlusion_is_bridged_by_prediction():
    tr = Tracker()
    for i in range(5):
        tr.update([car(100 + 40 * i)], at(i))
    for i in range(5, 8):  # ถูกบัง 3 เฟรม (0.6 วินาที) รถยังวิ่งต่อ
        tr.update([], at(i))
    seen, ended = tr.update([car(100 + 40 * 8)], at(8))
    assert [t.track_id for t in seen] == [1]
    assert not ended


def test_low_score_detection_keeps_existing_track_but_never_starts_one():
    tr = Tracker()
    tr.update([car(100)], at(0))
    seen, _ = tr.update([car(110, score=0.3)], at(1))
    assert [t.track_id for t in seen] == [1]
    seen, _ = tr.update([car(100), car(800, score=0.3)], at(2))
    assert [t.track_id for t in seen] == [1]  # กรอบความมั่นใจต่ำที่ไม่มีคู่ ไม่เปิด track ใหม่


def test_track_ends_after_max_lost():
    tr = Tracker()
    tr.update([car(100)], at(0))
    _, ended = tr.update([], at(5))  # 1 วินาที
    assert not ended
    _, ended = tr.update([], at(15))  # 3 วินาที > 2
    assert [t.track_id for t in ended] == [1]
    assert not tr.tracks


def test_majority_label():
    tr = Tracker()
    tr.update([Detection(Box(0, 0, 100, 100), "truck", 0.9)], at(0))
    for i in range(1, 4):
        tr.update([Detection(Box(0, 0, 100, 100), "car", 0.9)], at(i))
    assert tr.tracks[1].label == "car"


def test_flush_returns_everything():
    tr = Tracker()
    tr.update([car(100), car(600)], at(0))
    assert len(tr.flush()) == 2 and not tr.tracks
