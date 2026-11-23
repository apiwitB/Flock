"""ทดสอบครบวงจรด้วยภาพสังเคราะห์และโมเดลจำลอง: รถ 2 คันวิ่งผ่านกล้อง"""

from datetime import UTC, datetime, timedelta

import cv2
import numpy as np

from flock_contracts import SightingEvent
from flock_contracts.stream import EVENT_FIELD, STREAM
from flock_vision.bestshot import BestShotConfig, BestShotSelector, PlateReading
from flock_vision.geometry import Box, Detection
from flock_vision.pipeline import CameraPipeline
from flock_vision.sink import ImageStore, QueuePublisher

T0 = datetime(2026, 11, 23, 1, 0, tzinfo=UTC)
FPS = 5


def car_box(name: str, i: int) -> Box | None:
    """รถ A วิ่งซ้ายไปขวาเฟรม 0-14, รถ B วิ่งขวาไปซ้ายเฟรม 5-19"""
    if name == "A" and 0 <= i < 15:
        x = 20 + 40 * i
        return Box(x, 300, x + 300, 500)
    if name == "B" and 5 <= i < 20:
        x = 1500 - 40 * (i - 5)
        return Box(x, 600, x + 320, 820)
    return None


class ScriptedDetector:
    version = "scripted"

    def __init__(self, kind: str):
        self.kind = kind
        self.i = -1

    def detect(self, frame):
        self.i = int(frame[0, 0, 0])  # หมายเลขเฟรมฝังไว้ที่พิกเซลแรก
        out = []
        for name, label in (("A", "car"), ("B", "truck")):
            b = car_box(name, self.i)
            if b is None:
                continue
            if self.kind == "vehicle":
                out.append(Detection(b, label, 0.9))
            else:
                cx = (b.x1 + b.x2) / 2
                out.append(Detection(Box(cx - 60, b.y2 - 50, cx + 60, b.y2 - 15), "plate", 0.8))
        return out


class ScriptedReader:
    """OCR จำลอง: รถ A อ่านผิดเป็นบางเฟรม, รถ B ถูกตลอด แยกรถจากตำแหน่งแนวตั้งของภาพป้าย"""

    version = "scripted-ocr"

    def __init__(self):
        self.n = 0

    def read(self, plate):
        self.n += 1
        if plate.shape[0] and plate.mean() < 128:  # ป้ายของรถ A ถูกวาดสีเข้ม
            text = "1กช1234" if self.n % 4 == 0 else "1กข1234"
            return PlateReading(text, 0.85, "กรุงเทพมหานคร", 0.9)
        return PlateReading("9ฮฮ9", 0.9, "ชลบุรี", 0.8)


def render(i: int) -> np.ndarray:
    img = np.random.default_rng(i).integers(60, 200, (1080, 1920, 3), dtype=np.uint8)
    for name, plate_color in (("A", 40), ("B", 230)):
        b = car_box(name, i)
        if b is not None:
            cx = int((b.x1 + b.x2) / 2)
            cv2.rectangle(img, (int(b.x1), int(b.y1)), (int(b.x2), int(b.y2)), (200, 50, 50), -1)
            cv2.rectangle(img, (cx - 60, int(b.y2) - 50), (cx + 60, int(b.y2) - 15), (plate_color,) * 3, -1)
    img[0, 0] = i
    return img


class FakeRedis:
    def __init__(self):
        self.added = []

    def xadd(self, stream, fields, **kw):
        self.added.append((stream, fields, kw))


def run(tmp_path, frames=30):
    redis = FakeRedis()
    pipe = CameraPipeline(
        "G-entry", vehicle_detector=ScriptedDetector("vehicle"), plate_detector=ScriptedDetector("plate"),
        plate_reader=ScriptedReader(), store=ImageStore(tmp_path), publish=QueuePublisher(redis),
        selector=BestShotSelector(BestShotConfig(min_hits=3, emit_after_seconds=60)), run_id="r1",
    )
    events = []
    for i in range(frames):
        events += pipe.process(T0 + timedelta(seconds=i / FPS), render(i))
    events += pipe.close(T0 + timedelta(seconds=frames / FPS))
    return events, redis


def test_two_cars_give_one_event_each_with_voted_plates(tmp_path):
    events, redis = run(tmp_path)
    assert len(events) == 2
    by_plate = {e.plate.text: e for e in events}
    assert set(by_plate) == {"1กข1234", "9ฮฮ9"}  # OCR อ่านผิดบางเฟรม แต่ผลโหวตถูก

    a = by_plate["1กข1234"]
    assert a.plate.province == "กรุงเทพมหานคร"
    assert a.plate.confidence < 0.85  # มีเฟรมที่อ่านไม่ตรงกัน ความมั่นใจจึงลดลง
    assert a.attributes["vehicle_type"].value == "car"
    assert by_plate["9ฮฮ9"].attributes["vehicle_type"].value == "truck"
    assert a.track_id.startswith("G-entry.r1.")
    assert a.reader_versions == {"vehicle_det": "scripted", "plate_det": "scripted", "plate": "scripted-ocr"}
    assert T0 <= a.observed_at <= T0 + timedelta(seconds=3)


def test_images_written_before_publish_and_events_round_trip(tmp_path):
    events, redis = run(tmp_path)
    assert [s for s, _, _ in redis.added] == [STREAM, STREAM]
    for (_, fields, kw), ev in zip(redis.added, events):
        assert SightingEvent.model_validate_json(fields[EVENT_FIELD]) == ev
        assert kw["approximate"] is True
        for rel in (ev.images.crop_path, ev.images.context_path):
            assert rel.startswith("2026-11-23/G-entry/")
            img = cv2.imread(str(tmp_path / rel))
            assert img is not None and img.size > 0
        ctx = cv2.imread(str(tmp_path / ev.images.context_path))
        assert ctx.shape[1] == 960  # ย่อจาก 1920
    assert not list(tmp_path.rglob("*.tmp"))


def test_without_plate_models_events_have_no_plate(tmp_path):
    pipe = CameraPipeline("G-entry", vehicle_detector=ScriptedDetector("vehicle"), plate_detector=None,
                          plate_reader=None, store=ImageStore(tmp_path), publish=lambda e: None)
    events = []
    for i in range(30):
        events += pipe.process(T0 + timedelta(seconds=i / FPS), render(i))
    events += pipe.close(T0 + timedelta(seconds=6))
    assert len(events) == 2 and all(e.plate is None for e in events)
    assert pipe.reader_versions == {"vehicle_det": "scripted"}


def test_queue_outage_does_not_lose_events(tmp_path):
    down = {"on": True}
    published = []

    def flaky(ev):
        if down["on"]:
            raise ConnectionError("queue down")
        published.append(ev)

    pipe = CameraPipeline("G-entry", vehicle_detector=ScriptedDetector("vehicle"), plate_detector=None,
                          plate_reader=None, store=ImageStore(tmp_path), publish=flaky)
    for i in range(30):  # คิวล่มตลอดช่วงที่รถวิ่งผ่าน กล้องต้องทำงานต่อได้
        assert pipe.process(T0 + timedelta(seconds=i / FPS), render(i)) == []
    assert pipe.close(T0 + timedelta(seconds=6)) == []
    assert len(pipe._pending) == 2

    down["on"] = False  # คิวกลับมา: event ที่ค้างถูกส่งในรอบถัดไป
    sent = pipe.process(T0 + timedelta(seconds=7), render(40))
    assert len(sent) == 2 and published == sent and not pipe._pending


def test_pending_buffer_is_bounded(tmp_path):
    def down(ev):
        raise ConnectionError

    pipe = CameraPipeline("G-entry", vehicle_detector=ScriptedDetector("vehicle"), plate_detector=None,
                          plate_reader=None, store=ImageStore(tmp_path), publish=down, max_pending=1)
    for i in range(30):
        pipe.process(T0 + timedelta(seconds=i / FPS), render(i))
    pipe.close(T0 + timedelta(seconds=6))
    assert len(pipe._pending) == 1
