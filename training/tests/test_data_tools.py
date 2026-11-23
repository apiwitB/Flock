import json
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from flock_train.common import frame_name, parse_frame_name, read_tsv
from flock_train.cvat_convert import convert, split_of
from flock_train.eval_ocr import align_substitutions, evaluate


def test_frame_name_round_trip():
    name = frame_name("B1-ramp", datetime(2026, 11, 23, 8, 15, 3), 42)
    assert name == "B1-ramp_20261123T081503_000042.jpg"
    info = parse_frame_name(name)
    assert info.camera == "B1-ramp" and info.taken_at == datetime(2026, 11, 23, 8, 15, 3)
    assert parse_frame_name("random.jpg") is None


def test_split_groups_by_camera_and_hour():
    a = split_of("cam1_20261123T081500_000001.jpg", 10, 10)
    b = split_of("cam1_20261123T085959_009999.jpg", 10, 10)
    assert a == b  # ชั่วโมงเดียวกัน กล้องเดียวกัน ต้องอยู่ชุดเดียวกันเสมอ
    names = [f"cam{c}_202611{d:02d}T{h:02d}0000_000001.jpg" for c in range(3) for d in range(1, 15) for h in range(24)]
    splits = {split_of(n, 10, 10) for n in names}
    assert splits == {"train", "val", "test"}


BOX = '<box label="plate" xtl="{x}" ytl="100" xbr="{x2}" ybr="160" occluded="0" z_order="0">{attrs}</box>'


def attrs(**kw):
    return "".join(f'<attribute name="{k}">{v}</attribute>' for k, v in kw.items())


@pytest.fixture
def cvat(tmp_path: Path):
    frames = tmp_path / "frames"
    frames.mkdir()
    name = "cam1_20261123T081500_000001.jpg"
    Image.new("RGB", (640, 360), "gray").save(frames / name)
    boxes = [
        BOX.format(x=10, x2=130, attrs=attrs(text="1กข 1234", province="กทม", readable="true", plate_type="car")),
        BOX.format(x=150, x2=270, attrs=attrs(text="กข1234", province="ไม่มีจังหวัดนี้", readable="true")),
        BOX.format(x=290, x2=410, attrs=attrs(text="", province="", readable="false")),
        BOX.format(x=430, x2=550, attrs=attrs(text="กข1234", province="ชลบุรี", plate_type="motorcycle")),
        BOX.format(x=560, x2=630, attrs=attrs(text="AB123", province="ชลบุรี", readable="true")),
    ]
    xml = tmp_path / "annotations.xml"
    xml.write_text(
        "<annotations>"
        f'<image id="0" name="{name}" width="640" height="360">{"".join(boxes)}</image>'
        '<image id="1" name="cam1_20261123T081600_000002.jpg" width="640" height="360"></image>'
        "</annotations>",
        encoding="utf-8",
    )
    return xml, frames, name


def test_convert(cvat, tmp_path):
    xml, frames, name = cvat
    out = tmp_path / "ds"
    report = convert(xml, frames, out)
    split = split_of(name, 10, 10)
    c = report["counts"][split]

    assert c["images"] == 1
    assert c["plates"] == 5  # ทุกกรอบใช้เทรนตัวตรวจจับได้ แม้อ่านไม่ออก
    assert c["ocr"] == 2
    assert c["province"] == 2  # ข้อความกับจังหวัดคัดแยกกัน: กล่องที่ 5 ข้อความผิดแต่จังหวัดถูก
    assert report["rejected"] == {
        "image_missing": 1,
        "province_unknown": 1,
        "unreadable": 1,
        "plate_type:motorcycle": 1,
        "text_bad_char": 1,
    }
    # กล่องที่ 2 ข้อความถูก แต่จังหวัดผิด → เข้า OCR แต่ไม่เข้าจังหวัด
    ocr = read_tsv(out / "ocr" / split / "labels.tsv")
    assert sorted(t for _, t in ocr) == ["1กข1234", "กข1234"]

    prov = read_tsv(out / "province" / split / "labels.tsv")
    assert [p for _, p in prov] == ["กรุงเทพมหานคร", "ชลบุรี"]

    crop = Image.open(ocr[0][0])
    assert crop.size == (120, 37)  # สูง 60 * 0.62
    assert Image.open(prov[0][0]).size == (120, 23)

    coco = json.loads((out / "det" / split / "annotations.json").read_text(encoding="utf-8"))
    assert coco["annotations"][0]["bbox"] == [10.0, 100.0, 120.0, 60.0]
    assert Path(coco["images"][0]["file_name"]).exists()


def test_alignment_and_metrics():
    assert align_substitutions("กข1234", "กช1234") == (1, [("ข", "ช")])
    assert align_substitutions("กข1234", "กข123")[0] == 1
    m = evaluate([("กข1234", "กข1234"), ("กข1234", "กช1234"), ("ศพ88", "สพ88")])
    assert m["samples"] == 3
    assert m["exact_match"] == pytest.approx(1 / 3)
    assert m["cer"] == pytest.approx(2 / 16)
    assert {tuple(p["pair"]) for p in m["confusion_pairs"]} == {("ข", "ช"), ("ศ", "ส")}
