"""OCR บรรทัดเลขทะเบียน: CRNN + CTC (PyTorch ล้วน ไม่พึ่ง repo ภายนอก)

ป้ายไทยสั้น (ไม่เกิน 7 ตัว) และฟอนต์ค่อนข้างคงที่ CRNN+CTC จึงพอสำหรับรุ่นแรก
ถ้าความแม่นไม่พอค่อยลอง PARSeq ซึ่งจะใช้ชุดข้อมูลเดียวกันนี้ได้

    python -m flock_train.ocr train  --data datasets/v1/ocr --out runs/ocr
    python -m flock_train.ocr export --ckpt runs/ocr/best.pt --out runs/ocr/plate_ocr.onnx
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision.transforms import v2 as T

from flock_contracts.plates import OCR_CHARSET
from flock_train.common import read_tsv, write_tsv
from flock_train.eval_ocr import evaluate

H, W = 48, 160
BLANK = 0
CHAR_TO_ID = {c: i + 1 for i, c in enumerate(OCR_CHARSET)}


def encode(text: str) -> list[int]:
    return [CHAR_TO_ID[c] for c in text]


def greedy_decode(logits: torch.Tensor) -> list[str]:
    """logits: (T, N, C) → ข้อความ N ตัว (ยุบตัวซ้ำ แล้วตัด blank)"""
    out = []
    for seq in logits.argmax(-1).T.tolist():
        chars, prev = [], BLANK
        for k in seq:
            if k != prev and k != BLANK:
                chars.append(OCR_CHARSET[k - 1])
            prev = k
        out.append("".join(chars))
    return out


def _block(cin: int, cout: int) -> list[nn.Module]:
    return [nn.Conv2d(cin, cout, 3, padding=1, bias=False), nn.BatchNorm2d(cout), nn.ReLU(inplace=True)]


class CRNN(nn.Module):
    def __init__(self, num_classes: int = len(OCR_CHARSET) + 1):
        super().__init__()
        self.cnn = nn.Sequential(
            *_block(3, 32), nn.MaxPool2d(2),  # 24x80
            *_block(32, 64), nn.MaxPool2d(2),  # 12x40
            *_block(64, 128), *_block(128, 128), nn.MaxPool2d((2, 1)),  # 6x40
            *_block(128, 256), *_block(256, 256), nn.MaxPool2d((2, 1)),  # 3x40
            nn.Conv2d(256, 256, (3, 1), bias=False), nn.BatchNorm2d(256), nn.ReLU(inplace=True),  # 1x40
        )
        self.rnn = nn.LSTM(256, 128, num_layers=2, bidirectional=True, dropout=0.1)
        self.head = nn.Linear(256, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        f = self.cnn(x).squeeze(2).permute(2, 0, 1)  # (T, N, 256)
        f, _ = self.rnn(f)
        return self.head(f)  # (T, N, C)


def transforms(train: bool) -> T.Compose:
    base = [T.Resize((H, W), antialias=True)]
    if train:
        base += [
            T.RandomApply([T.RandomAffine(degrees=4, translate=(0.03, 0.06), scale=(0.92, 1.05), shear=6)], p=0.7),
            T.RandomApply([T.RandomPerspective(distortion_scale=0.15, p=1.0)], p=0.3),
            T.ColorJitter(0.5, 0.5, 0.4, 0.05),  # กลางวัน/กลางคืน/ไฟหน้า
            T.RandomApply([T.GaussianBlur(5, sigma=(0.1, 1.5))], p=0.3),
        ]
    return T.Compose([T.ToImage(), *base, T.ToDtype(torch.float32, scale=True), T.Normalize([0.5] * 3, [0.5] * 3)])


class PlateTextDataset(Dataset):
    def __init__(self, tsv: Path, train: bool):
        self.rows = read_tsv(tsv)
        self.tf = transforms(train)

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, i: int):
        path, text = self.rows[i]
        return self.tf(Image.open(path).convert("RGB")), text, str(path)


def collate(batch):
    imgs, texts, paths = zip(*batch)
    targets = torch.tensor([k for t in texts for k in encode(t)], dtype=torch.long)
    lengths = torch.tensor([len(t) for t in texts], dtype=torch.long)
    return torch.stack(imgs), targets, lengths, list(texts), list(paths)


@torch.no_grad()
def predict(model: nn.Module, loader: DataLoader, device: torch.device) -> list[tuple[str, str, str]]:
    model.eval()
    rows = []
    for imgs, _, _, texts, paths in loader:
        preds = greedy_decode(model(imgs.to(device)).float().cpu())
        rows += list(zip(paths, texts, preds))
    return rows


def train(a: argparse.Namespace) -> None:
    torch.manual_seed(a.seed)
    random.seed(a.seed)
    device = torch.device("cuda" if torch.cuda.is_available() and not a.cpu else "cpu")
    use_amp = device.type == "cuda"
    out = a.out
    out.mkdir(parents=True, exist_ok=True)

    train_ds = PlateTextDataset(a.data / "train" / "labels.tsv", train=True)
    val_ds = PlateTextDataset(a.data / "val" / "labels.tsv", train=False)
    if not train_ds or not val_ds:
        raise SystemExit("ชุด train หรือ val ว่าง")
    dl = dict(batch_size=a.batch, num_workers=a.workers, collate_fn=collate, pin_memory=use_amp)
    train_dl = DataLoader(train_ds, shuffle=True, drop_last=len(train_ds) > a.batch, **dl)
    val_dl = DataLoader(val_ds, shuffle=False, **dl)

    model = CRNN().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=a.epochs * len(train_dl))
    scaler = torch.amp.GradScaler(enabled=use_amp)
    ctc = nn.CTCLoss(blank=BLANK, zero_infinity=True)

    best = -1.0
    history = []
    for epoch in range(1, a.epochs + 1):
        model.train()
        t0, total = time.time(), 0.0
        for imgs, targets, lengths, _, _ in train_dl:
            imgs = imgs.to(device, non_blocking=True)
            with torch.autocast(device.type, dtype=torch.float16, enabled=use_amp):
                logits = model(imgs)
            log_probs = logits.float().log_softmax(-1)
            in_len = torch.full((imgs.size(0),), log_probs.size(0), dtype=torch.long)
            loss = ctc(log_probs, targets, in_len, lengths)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            scaler.step(opt)
            scaler.update()
            sched.step()
            total += loss.item()

        metrics = evaluate([(gt, pr) for _, gt, pr in predict(model, val_dl, device)])
        row = {"epoch": epoch, "loss": total / len(train_dl), "val_exact": metrics["exact_match"],
               "val_cer": metrics["cer"], "sec": round(time.time() - t0, 1)}
        history.append(row)
        print(json.dumps(row))
        if metrics["exact_match"] > best:
            best = metrics["exact_match"]
            torch.save({"model": model.state_dict(), "charset": OCR_CHARSET, "h": H, "w": W, "epoch": epoch}, out / "best.pt")

    (out / "history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")

    test_tsv = a.data / "test" / "labels.tsv"
    if test_tsv.exists() and read_tsv(test_tsv):
        model.load_state_dict(torch.load(out / "best.pt", map_location=device)["model"])
        test_dl = DataLoader(PlateTextDataset(test_tsv, train=False), shuffle=False, **dl)
        rows = predict(model, test_dl, device)
        write_tsv(out / "test_predictions.tsv", rows)
        m = evaluate([(gt, pr) for _, gt, pr in rows])
        (out / "test_eval.json").write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"test_exact": m["exact_match"], "test_cer": m["cer"]}))


def export(a: argparse.Namespace) -> None:
    ckpt = torch.load(a.ckpt, map_location="cpu")
    if ckpt["charset"] != OCR_CHARSET:
        raise SystemExit("charset ใน checkpoint ไม่ตรงกับ flock_contracts.OCR_CHARSET")
    model = CRNN()
    model.load_state_dict(ckpt["model"])
    model.eval()
    torch.onnx.export(
        model, torch.zeros(1, 3, H, W), str(a.out), input_names=["image"], output_names=["logits"],
        dynamic_axes={"image": {0: "batch"}, "logits": {1: "batch"}}, opset_version=17, dynamo=False,
    )
    print(a.out)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--data", type=Path, required=True)
    t.add_argument("--out", type=Path, required=True)
    t.add_argument("--epochs", type=int, default=60)
    t.add_argument("--batch", type=int, default=128)
    t.add_argument("--lr", type=float, default=1e-3)
    t.add_argument("--workers", type=int, default=4)
    t.add_argument("--seed", type=int, default=0)
    t.add_argument("--cpu", action="store_true")
    e = sub.add_parser("export")
    e.add_argument("--ckpt", type=Path, required=True)
    e.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    train(a) if a.cmd == "train" else export(a)


if __name__ == "__main__":
    main()
