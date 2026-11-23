"""อ่านป้ายด้วยโมเดล ONNX ที่ export จาก training/

การเตรียมภาพต้องตรงกับตอนเทรน (training/flock_train/ocr.py และ province.py):
- แบ่งป้ายรถยนต์เป็นบรรทัดบน (เลขทะเบียน) และบรรทัดล่าง (จังหวัด) ที่สัดส่วน text_split เท่ากับตอนแปลงชุดข้อมูล
- OCR: RGB 48x160, normalize mean 0.5 std 0.5, output (T, N, C) logits, blank = 0
- จังหวัด: RGB 64x224, normalize ImageNet, output (N, 78) logits ตามลำดับ PROVINCES
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import cv2
import numpy as np

from flock_contracts import PROVINCES, is_standard_plate
from flock_contracts.plates import OCR_CHARSET
from flock_vision.bestshot import PlateReading

OCR_H, OCR_W = 48, 160
PROV_H, PROV_W = 64, 224
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
# ข้อความที่ไม่ตรงรูปแบบป้ายมาตรฐาน (เช่น อ่านขาดตัว) ถูกลดความมั่นใจลง
NON_STANDARD_PENALTY = 0.5


class PlateRecognizer(Protocol):
    version: str

    def read(self, plate_bgr: np.ndarray) -> PlateReading | None: ...


def _softmax(x: np.ndarray, axis: int = -1) -> np.ndarray:
    e = np.exp(x - x.max(axis=axis, keepdims=True))
    return e / e.sum(axis=axis, keepdims=True)


def _to_input(img_bgr: np.ndarray, h: int, w: int, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    rgb = cv2.cvtColor(cv2.resize(img_bgr, (w, h), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    x = (rgb.astype(np.float32) / 255.0 - mean) / std
    return np.ascontiguousarray(x.transpose(2, 0, 1)[None])


def ctc_decode(logits: np.ndarray) -> tuple[str, float]:
    """logits (T, C) ของภาพเดียว → (ข้อความ, ความมั่นใจ)

    ความมั่นใจ = ค่าต่ำสุดของความน่าจะเป็นของตัวอักษรที่อ่านได้ (ตัวที่ไม่แน่ใจที่สุดกำหนดความมั่นใจของทั้งป้าย)"""
    probs = _softmax(logits.astype(np.float32), axis=-1)
    best = probs.argmax(-1)
    chars, confs, prev = [], [], 0
    for t, k in enumerate(best):
        k = int(k)
        if k != prev and k != 0:
            chars.append(OCR_CHARSET[k - 1])
            confs.append(float(probs[t, k]))
        prev = k
    return "".join(chars), (min(confs) if confs else 0.0)


class OnnxPlateReader:
    def __init__(self, ocr_model: str, province_model: str | None = None, *, text_split: float = 0.62,
                 version: str = "onnx", session_factory: Callable[[str], Any] | None = None):
        if session_factory is None:
            import onnxruntime as ort

            providers = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in ort.get_available_providers()]
            session_factory = lambda path: ort.InferenceSession(path, providers=providers)  # noqa: E731
        self.ocr = session_factory(ocr_model)
        self.province = session_factory(province_model) if province_model else None
        self.text_split = text_split
        self.version = version

    def read(self, plate_bgr: np.ndarray) -> PlateReading | None:
        h = plate_bgr.shape[0]
        cut = max(1, int(round(h * self.text_split)))
        top, bottom = plate_bgr[:cut], plate_bgr[cut:]
        if top.size == 0:
            return None

        logits = self.ocr.run(None, {"image": _to_input(top, OCR_H, OCR_W, np.float32(0.5), np.float32(0.5))})[0]
        text, conf = ctc_decode(logits[:, 0, :])
        if not text:
            return None
        if not is_standard_plate(text):
            conf *= NON_STANDARD_PENALTY

        province = province_conf = None
        if self.province is not None and bottom.size:
            p = _softmax(self.province.run(None, {"image": _to_input(bottom, PROV_H, PROV_W, IMAGENET_MEAN,
                                                                      IMAGENET_STD)})[0][0])
            idx = int(p.argmax())
            province, province_conf = PROVINCES[idx], float(p[idx])
        return PlateReading(text, round(conf, 4), province, None if province_conf is None else round(province_conf, 4))
