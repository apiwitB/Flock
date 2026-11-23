"""จำแนกจังหวัดจากบรรทัดล่างของป้าย (78 คลาส ตามลำดับใน flock_contracts.PROVINCES)

    python -m flock_train.province train  --data datasets/v1/province --out runs/province
    python -m flock_train.province export --ckpt runs/province/best.pt --out runs/province/province.onnx

หมายเหตุใบอนุญาต: weights ImageNet ของ timm ใช้ได้ แต่ชุดข้อมูล ImageNet มีเงื่อนไขเชิงพาณิชย์ที่ไม่ชัด
ถ้าต้องการตัดความเสี่ยงให้ใช้ --no-pretrained (ต้องมีข้อมูลมากขึ้น)
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import timm
import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision.transforms import v2 as T

from flock_contracts import PROVINCES
from flock_train.common import read_tsv

H, W = 64, 224
INDEX = {p: i for i, p in enumerate(PROVINCES)}


def transforms(train: bool) -> T.Compose:
    aug = []
    if train:
        aug = [
            T.RandomApply([T.RandomAffine(degrees=3, translate=(0.04, 0.08), scale=(0.9, 1.05))], p=0.7),
            T.ColorJitter(0.5, 0.5, 0.4, 0.05),
            T.RandomApply([T.GaussianBlur(5, sigma=(0.1, 1.5))], p=0.3),
        ]
    return T.Compose([
        T.ToImage(), T.Resize((H, W), antialias=True), *aug,
        T.ToDtype(torch.float32, scale=True), T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])


class ProvinceDataset(Dataset):
    def __init__(self, tsv: Path, train: bool):
        self.rows = [(p, INDEX[name]) for p, name in read_tsv(tsv)]
        self.tf = transforms(train)

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, i: int):
        path, label = self.rows[i]
        return self.tf(Image.open(path).convert("RGB")), label


def build(arch: str, pretrained: bool) -> nn.Module:
    return timm.create_model(arch, pretrained=pretrained, num_classes=len(PROVINCES))


@torch.no_grad()
def accuracy(model: nn.Module, loader: DataLoader, device: torch.device) -> float:
    model.eval()
    correct = total = 0
    for x, y in loader:
        correct += (model(x.to(device)).argmax(1).cpu() == y).sum().item()
        total += len(y)
    return correct / total if total else 0.0


def train(a: argparse.Namespace) -> None:
    torch.manual_seed(a.seed)
    device = torch.device("cuda" if torch.cuda.is_available() and not a.cpu else "cpu")
    use_amp = device.type == "cuda"
    a.out.mkdir(parents=True, exist_ok=True)

    train_ds = ProvinceDataset(a.data / "train" / "labels.tsv", True)
    val_ds = ProvinceDataset(a.data / "val" / "labels.tsv", False)
    if not train_ds or not val_ds:
        raise SystemExit("ชุด train หรือ val ว่าง")
    counts = Counter(y for _, y in train_ds.rows)
    print("จังหวัดที่มีในชุด train:", len(counts), "/", len(PROVINCES))

    dl = dict(batch_size=a.batch, num_workers=a.workers, pin_memory=use_amp)
    train_dl = DataLoader(train_ds, shuffle=True, drop_last=len(train_ds) > a.batch, **dl)
    val_dl = DataLoader(val_ds, shuffle=False, **dl)

    model = build(a.arch, not a.no_pretrained).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.05)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=a.epochs * len(train_dl))
    scaler = torch.amp.GradScaler(enabled=use_amp)
    loss_fn = nn.CrossEntropyLoss(label_smoothing=0.1)

    best, history = -1.0, []
    for epoch in range(1, a.epochs + 1):
        model.train()
        t0, total = time.time(), 0.0
        for x, y in train_dl:
            x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
            with torch.autocast(device.type, dtype=torch.float16, enabled=use_amp):
                loss = loss_fn(model(x), y)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
            sched.step()
            total += loss.item()
        acc = accuracy(model, val_dl, device)
        row = {"epoch": epoch, "loss": total / len(train_dl), "val_acc": acc, "sec": round(time.time() - t0, 1)}
        history.append(row)
        print(json.dumps(row))
        if acc > best:
            best = acc
            torch.save({"model": model.state_dict(), "arch": a.arch, "provinces": list(PROVINCES), "h": H, "w": W},
                       a.out / "best.pt")
    (a.out / "history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")


def export(a: argparse.Namespace) -> None:
    ckpt = torch.load(a.ckpt, map_location="cpu")
    if ckpt["provinces"] != list(PROVINCES):
        raise SystemExit("ลำดับจังหวัดใน checkpoint ไม่ตรงกับ flock_contracts.PROVINCES")
    model = build(ckpt["arch"], pretrained=False)
    model.load_state_dict(ckpt["model"])
    model.eval()
    torch.onnx.export(
        model, torch.zeros(1, 3, H, W), str(a.out), input_names=["image"], output_names=["logits"],
        dynamic_axes={"image": {0: "batch"}, "logits": {0: "batch"}}, opset_version=17, dynamo=False,
    )
    print(a.out)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--data", type=Path, required=True)
    t.add_argument("--out", type=Path, required=True)
    t.add_argument("--arch", default="resnet18")
    t.add_argument("--epochs", type=int, default=30)
    t.add_argument("--batch", type=int, default=128)
    t.add_argument("--lr", type=float, default=1e-3)
    t.add_argument("--workers", type=int, default=4)
    t.add_argument("--seed", type=int, default=0)
    t.add_argument("--no-pretrained", action="store_true")
    t.add_argument("--cpu", action="store_true")
    e = sub.add_parser("export")
    e.add_argument("--ckpt", type=Path, required=True)
    e.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    train(a) if a.cmd == "train" else export(a)


if __name__ == "__main__":
    main()
