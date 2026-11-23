import threading
from datetime import UTC, datetime, timedelta

import cv2
import numpy as np
import pytest

from flock_contracts import PROVINCES
from flock_contracts.plates import OCR_CHARSET
from flock_vision.readers import OnnxPlateReader, ctc_decode
from flock_vision.source import VideoSource, _redact

C = len(OCR_CHARSET) + 1


def logits_for(seq: list[str | None], strength: float = 10.0) -> np.ndarray:
    """None = blank"""
    out = np.zeros((len(seq), C), dtype=np.float32)
    for t, ch in enumerate(seq):
        out[t, 0 if ch is None else OCR_CHARSET.index(ch) + 1] = strength
    return out


def test_ctc_decode_collapses_and_reports_weakest_char():
    text, conf = ctc_decode(logits_for(["1", "1", None, "ก", "ข", None, "1", "2", "3", "4"]))
    assert text == "1กข1234"
    assert 0.99 < conf <= 1.0
    weak = logits_for(["ก", "ข", "1"])
    weak[1, OCR_CHARSET.index("ช") + 1] = 9.5  # ลังเลระหว่าง ข กับ ช
    text, conf = ctc_decode(weak)
    assert text == "กข1" and conf < 0.7


class FakeSession:
    def __init__(self, output: np.ndarray):
        self.output = output
        self.inputs = []

    def run(self, _names, feeds):
        self.inputs.append(feeds["image"])
        return [self.output]


def make_reader(ocr_seq, province_idx=None, **kw):
    ocr = FakeSession(logits_for(ocr_seq)[:, None, :])
    prov = None
    if province_idx is not None:
        p = np.zeros((1, len(PROVINCES)), dtype=np.float32)
        p[0, province_idx] = 8.0
        prov = FakeSession(p)
    sessions = {"ocr.onnx": ocr, "prov.onnx": prov}
    reader = OnnxPlateReader("ocr.onnx", "prov.onnx" if prov else None, session_factory=sessions.__getitem__, **kw)
    return reader, ocr, prov


def test_reader_preprocessing_matches_training_and_splits_plate():
    reader, ocr, prov = make_reader(["1", "ก", "ข", "1", "2", "3", "4"], province_idx=PROVINCES.index("ชลบุรี"))
    plate = np.full((100, 300, 3), 255, dtype=np.uint8)
    reading = reader.read(plate)
    assert reading.text == "1กข1234" and reading.province == "ชลบุรี"
    assert reading.province_confidence > 0.9

    x = ocr.inputs[0]
    assert x.shape == (1, 3, 48, 160) and x.dtype == np.float32
    assert np.allclose(x, 1.0)  # ขาวล้วน → (1 - 0.5) / 0.5
    p = prov.inputs[0]
    assert p.shape == (1, 3, 64, 224)
    assert np.allclose(p[0, 0], (1 - 0.485) / 0.229, atol=1e-5)


def test_non_standard_text_is_penalised_and_empty_is_none():
    reader, _, _ = make_reader(["ก", "ข"])  # ไม่มีตัวเลข: ไม่ใช่ป้ายมาตรฐาน
    r = reader.read(np.zeros((40, 120, 3), dtype=np.uint8))
    assert r.text == "กข" and r.confidence == pytest.approx(0.5, abs=0.01)
    assert r.province is None
    reader, _, _ = make_reader([None, None])
    assert reader.read(np.zeros((40, 120, 3), dtype=np.uint8)) is None


def write_video(path, frames=50, fps=25.0):
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (160, 120))
    for i in range(frames):
        img = np.zeros((120, 160, 3), dtype=np.uint8)
        img[:, : 3 * i + 1] = 255
        w.write(img)
    w.release()


def test_file_source_downsamples_and_uses_video_time(tmp_path):
    path = tmp_path / "cam_20261123T080000.mp4"
    write_video(path)
    start = datetime(2026, 11, 23, 1, 0, tzinfo=UTC)
    src = VideoSource(str(path), target_fps=5, live=False, start_time=start)
    frames = list(src.frames(threading.Event()))
    assert 9 <= len(frames) <= 11  # 2 วินาทีที่ 5 fps
    gaps = [(b.at - a.at).total_seconds() for a, b in zip(frames, frames[1:])]
    assert all(abs(g - 0.2) < 0.05 for g in gaps)
    assert frames[0].at == start
    assert frames[0].image.shape == (120, 160, 3)


class FakeCap:
    def __init__(self, n_frames: int, opened: bool = True):
        self.n, self.opened, self.released = n_frames, opened, False

    def isOpened(self):
        return self.opened

    def grab(self):
        self.n -= 1
        return self.n >= 0

    def retrieve(self):
        return True, np.zeros((4, 4, 3), dtype=np.uint8)

    def get(self, _prop):
        return 0.0

    def release(self):
        self.released = True


def test_live_source_reconnects_after_failures():
    caps = iter([FakeCap(0, opened=False), FakeCap(3), FakeCap(0, opened=False), FakeCap(2)])
    t = [datetime(2026, 11, 23, tzinfo=UTC)]

    def clock():
        t[0] += timedelta(seconds=1)
        return t[0]

    stop = threading.Event()
    src = VideoSource("rtsp://u:secret@10.0.0.5/s", target_fps=5, live=True, opener=lambda _: next(caps),
                      clock=clock, initial_backoff=0.01)
    got = []
    for f in src.frames(stop):
        got.append(f)
        if len(got) == 5:
            stop.set()
    assert len(got) == 5  # 3 เฟรมจากการต่อครั้งแรก + 2 จากครั้งที่สอง


def test_password_is_redacted_from_logs():
    assert _redact("rtsp://admin:hunter2@10.0.0.5:554/s1") == "rtsp://***@10.0.0.5:554/s1"
    assert _redact("/clips/a.mp4") == "/clips/a.mp4"
