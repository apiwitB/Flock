"""Fine-tune ตัวตรวจจับป้าย (1 คลาส: plate) ด้วย RT-DETRv2 ของ Hugging Face transformers (Apache-2.0)

ตัวตรวจรถใช้ weights COCO สำเร็จรูป (car/motorcycle/bus/truck) ไม่ต้องเทรนในรุ่นแรก
สคริปต์นี้เทรนเฉพาะการหา "ป้าย" ในภาพเต็ม

    python -m flock_train.detector train --data datasets/v1/det --out runs/det

VRAM 8 GB: เริ่มที่ --batch 4 --size 640 ถ้า out-of-memory ให้ลด batch เป็น 2
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchmetrics.detection import MeanAveragePrecision
from transformers import AutoImageProcessor, AutoModelForObjectDetection

DEFAULT_CKPT = "PekingU/rtdetr_v2_r18vd"


class CocoPlates(Dataset):
    def __init__(self, ann_file: Path):
        coco = json.loads(ann_file.read_text(encoding="utf-8"))
        self.images = coco["images"]
        self.by_image: dict[int, list[dict]] = {}
        for a in coco["annotations"]:
            self.by_image.setdefault(a["image_id"], []).append(a)

    def __len__(self) -> int:
        return len(self.images)

    def __getitem__(self, i: int):
        info = self.images[i]
        anns = [{**a, "category_id": 0} for a in self.by_image.get(info["id"], [])]
        return Image.open(info["file_name"]).convert("RGB"), {"image_id": info["id"], "annotations": anns}


def make_collate(processor):
    def collate(batch):
        images, targets = zip(*batch)
        enc = processor(images=list(images), annotations=list(targets), return_tensors="pt")
        sizes = [img.size[::-1] for img in images]  # (h, w)
        return enc["pixel_values"], enc["labels"], list(targets), sizes
    return collate


@torch.no_grad()
def evaluate(model, processor, loader, device) -> dict:
    model.eval()
    metric = MeanAveragePrecision(box_format="xyxy", iou_type="bbox")
    for pixel_values, _, targets, sizes in loader:
        out = model(pixel_values=pixel_values.to(device))
        preds = processor.post_process_object_detection(out, threshold=0.0, target_sizes=sizes)
        gts = []
        for t in targets:
            boxes = torch.tensor([[x, y, x + w, y + h] for x, y, w, h in (a["bbox"] for a in t["annotations"])],
                                 dtype=torch.float32).reshape(-1, 4)
            gts.append({"boxes": boxes, "labels": torch.zeros(len(boxes), dtype=torch.long)})
        metric.update([{k: v.cpu() for k, v in p.items()} for p in preds], gts)
    r = metric.compute()
    return {"map": float(r["map"]), "map_50": float(r["map_50"]), "mar_100": float(r["mar_100"])}


def train(a: argparse.Namespace) -> None:
    torch.manual_seed(a.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    use_amp = device.type == "cuda"
    a.out.mkdir(parents=True, exist_ok=True)

    processor = AutoImageProcessor.from_pretrained(a.ckpt, size={"height": a.size, "width": a.size})
    model = AutoModelForObjectDetection.from_pretrained(
        a.ckpt, id2label={0: "plate"}, label2id={"plate": 0}, ignore_mismatched_sizes=True
    ).to(device)

    collate = make_collate(processor)
    train_dl = DataLoader(CocoPlates(a.data / "train" / "annotations.json"), batch_size=a.batch, shuffle=True,
                          num_workers=a.workers, collate_fn=collate)
    val_dl = DataLoader(CocoPlates(a.data / "val" / "annotations.json"), batch_size=a.batch, shuffle=False,
                        num_workers=a.workers, collate_fn=collate)

    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=a.epochs * len(train_dl), pct_start=0.1)
    scaler = torch.amp.GradScaler(enabled=use_amp)

    best, history = -1.0, []
    for epoch in range(1, a.epochs + 1):
        model.train()
        t0, total = time.time(), 0.0
        for pixel_values, labels, _, _ in train_dl:
            labels = [{k: v.to(device) for k, v in lab.items()} for lab in labels]
            with torch.autocast(device.type, dtype=torch.float16, enabled=use_amp):
                loss = model(pixel_values=pixel_values.to(device), labels=labels).loss
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 0.1)
            scaler.step(opt)
            scaler.update()
            sched.step()
            total += loss.item()
        m = evaluate(model, processor, val_dl, device)
        row = {"epoch": epoch, "loss": total / len(train_dl), **{f"val_{k}": v for k, v in m.items()},
               "sec": round(time.time() - t0, 1)}
        history.append(row)
        print(json.dumps(row))
        if m["map_50"] > best:
            best = m["map_50"]
            model.save_pretrained(a.out / "best")
            processor.save_pretrained(a.out / "best")
    (a.out / "history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--data", type=Path, required=True)
    t.add_argument("--out", type=Path, required=True)
    t.add_argument("--ckpt", default=DEFAULT_CKPT)
    t.add_argument("--size", type=int, default=640)
    t.add_argument("--epochs", type=int, default=40)
    t.add_argument("--batch", type=int, default=4)
    t.add_argument("--lr", type=float, default=1e-4)
    t.add_argument("--workers", type=int, default=4)
    t.add_argument("--seed", type=int, default=0)
    a = p.parse_args()
    train(a)


if __name__ == "__main__":
    main()
