"""รันเทรนแบบสั้นมากบน CPU ด้วยภาพสุ่ม เพื่อยืนยันว่าสคริปต์ทำงานครบตั้งแต่ต้นจนจบ
(ไม่ได้วัดความแม่นยำ) ข้ามอัตโนมัติถ้าไม่ได้ติดตั้ง torch"""

import argparse
import json
import random

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("torchvision")

from PIL import Image  # noqa: E402

from flock_contracts import PROVINCES  # noqa: E402
from flock_train.common import write_tsv  # noqa: E402


def fake_split(root, split, labels, size):
    rows = []
    (root / split / "images").mkdir(parents=True)
    for i, label in enumerate(labels):
        rel = f"images/{i}.png"
        Image.effect_noise(size, random.randint(20, 80)).convert("RGB").save(root / split / rel)
        rows.append((rel, label))
    write_tsv(root / split / "labels.tsv", rows)


def test_ocr_train_and_export(tmp_path):
    from flock_train import ocr

    data = tmp_path / "ocr"
    texts = ["1กข1234", "ขค99", "ฮฮ1", "9ศส5678"]
    for split in ("train", "val", "test"):
        fake_split(data, split, texts * 2, (120, 37))
    out = tmp_path / "run"
    ocr.train(argparse.Namespace(data=data, out=out, epochs=2, batch=4, lr=1e-3, workers=0, seed=0, cpu=True))

    assert (out / "best.pt").exists()
    assert len(json.loads((out / "history.json").read_text())) == 2
    assert (out / "test_predictions.tsv").read_text(encoding="utf-8").count("\n") == 8

    pytest.importorskip("onnx")
    ocr.export(argparse.Namespace(ckpt=out / "best.pt", out=out / "ocr.onnx"))
    assert (out / "ocr.onnx").stat().st_size > 0

    # LSTM + dynamic batch เคยมีปัญหาใน ONNX: ยืนยันว่า batch > 1 ให้ผลเท่ากับ PyTorch
    ort = pytest.importorskip("onnxruntime")
    model = ocr.CRNN()
    model.load_state_dict(torch.load(out / "best.pt")["model"])
    model.eval()
    x = torch.randn(3, 3, ocr.H, ocr.W)
    expected = model(x).detach().numpy()
    got = ort.InferenceSession(str(out / "ocr.onnx")).run(None, {"image": x.numpy()})[0]
    assert got.shape == expected.shape
    assert abs(got - expected).max() < 1e-3


def test_greedy_decode_collapses_repeats_and_blanks():
    from flock_train.ocr import BLANK, CHAR_TO_ID, greedy_decode

    k, x = CHAR_TO_ID["ก"], CHAR_TO_ID["1"]
    seq = [k, k, BLANK, k, x, x, BLANK]
    logits = torch.full((len(seq), 1, len(CHAR_TO_ID) + 1), -10.0)
    for t, c in enumerate(seq):
        logits[t, 0, c] = 10.0
    assert greedy_decode(logits) == ["กก1"]


def test_province_train_and_export(tmp_path):
    pytest.importorskip("timm")
    from flock_train import province

    data = tmp_path / "prov"
    names = list(PROVINCES[:3]) * 3
    for split in ("train", "val"):
        fake_split(data, split, names, (120, 23))
    out = tmp_path / "run"
    province.train(argparse.Namespace(data=data, out=out, arch="resnet18", epochs=1, batch=4, lr=1e-3, workers=0,
                                      seed=0, no_pretrained=True, cpu=True))
    assert (out / "best.pt").exists()

    pytest.importorskip("onnx")
    province.export(argparse.Namespace(ckpt=out / "best.pt", out=out / "province.onnx"))
    assert (out / "province.onnx").stat().st_size > 0
