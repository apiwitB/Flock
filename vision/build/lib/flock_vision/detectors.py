"""ตัวตรวจจับ (detector)

HFDetector ใช้ RT-DETRv2 ของ Hugging Face transformers ซึ่งเป็นตัวเดียวกับที่ training/ ใช้ fine-tune ตัวตรวจป้าย
- ตัวตรวจรถ: checkpoint COCO สำเร็จรูป (เช่น PekingU/rtdetr_v2_r18vd) เลือกเฉพาะคลาสรถ
- ตัวตรวจป้าย: checkpoint ที่เทรนเอง (runs/det-v1/best) คลาสเดียว "plate"

**ยังไม่ได้ทดสอบกับโมเดลจริง** ต้องรันบนเครื่อง GPU (ROADMAP B2, B6) ภายหลังควรเปลี่ยนเป็น TensorRT
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from flock_vision.geometry import Box, Detection

COCO_VEHICLES = {"car": "car", "motorcycle": "motorcycle", "bus": "bus", "truck": "truck"}


class Detector(Protocol):
    version: str

    def detect(self, frame_bgr: np.ndarray) -> list[Detection]: ...


class HFDetector:
    def __init__(self, checkpoint: str, *, keep: dict[str, str] | None = None, threshold: float = 0.1,
                 device: str | None = None, fp16: bool = True):
        """keep: map ชื่อคลาสของโมเดล → ชื่อที่ใช้ในระบบ (None = เก็บทุกคลาส)
        threshold ต่ำไว้ (0.1) เพราะ tracker ใช้กรอบความมั่นใจต่ำในการจับคู่รอบสอง"""
        import torch
        from transformers import AutoImageProcessor, AutoModelForObjectDetection

        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.dtype = torch.float16 if fp16 and self.device == "cuda" else torch.float32
        self.processor = AutoImageProcessor.from_pretrained(checkpoint)
        self.model = AutoModelForObjectDetection.from_pretrained(checkpoint).to(self.device, self.dtype).eval()
        self.keep = keep
        self.threshold = threshold
        self.version = checkpoint.rstrip("/").split("/")[-1]

    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        torch = self.torch
        rgb = frame_bgr[:, :, ::-1]
        inputs = self.processor(images=rgb, return_tensors="pt").to(self.device)
        with torch.inference_mode():
            out = self.model(pixel_values=inputs["pixel_values"].to(self.dtype))
        res = self.processor.post_process_object_detection(
            out, threshold=self.threshold, target_sizes=[frame_bgr.shape[:2]])[0]
        dets = []
        for score, label, box in zip(res["scores"].tolist(), res["labels"].tolist(), res["boxes"].tolist()):
            name = self.model.config.id2label[label]
            if self.keep is not None:
                if name not in self.keep:
                    continue
                name = self.keep[name]
            dets.append(Detection(Box(*box), name, float(score)))
        return dets
