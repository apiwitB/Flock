"""แปลงไฟล์ export จาก CVAT ("CVAT for images 1.1") เป็นชุดข้อมูลสำหรับเทรน 3 ชุด (ใช้ CPU)

    det/{split}/annotations.json     COCO: กรอบป้ายในภาพเต็ม (ภาพอ้างอิงจาก --images ไม่คัดลอก)
    ocr/{split}/labels.tsv           ภาพบรรทัดเลขทะเบียน + ข้อความ
    province/{split}/labels.tsv      ภาพบรรทัดจังหวัด + ชื่อจังหวัด
    report.json                      จำนวนต่อชุด และป้ายที่ถูกคัดออกพร้อมเหตุผล

แบ่ง train/val/test ตาม "กล้อง + ชั่วโมง" ไม่สุ่มทีละภาพ เพราะเฟรมติดกันเห็นรถคันเดียวกัน
ถ้าสุ่มทีละภาพ ผลวัดบน val/test จะดีเกินจริง

    python -m flock_train.cvat_convert annotations.xml --images frames --out datasets/v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from flock_contracts import is_standard_plate, normalize_province
from flock_contracts.plates import OCR_CHARSET, clean_plate_text
from flock_train.common import parse_frame_name, write_tsv

SPLITS = ("train", "val", "test")


@dataclass
class PlateBox:
    xtl: float
    ytl: float
    xbr: float
    ybr: float
    text: str | None
    province: str | None
    readable: bool
    plate_type: str


@dataclass
class ImageAnn:
    name: str
    width: int
    height: int
    plates: list[PlateBox] = field(default_factory=list)


def parse_cvat(xml_path: Path) -> list[ImageAnn]:
    images = []
    for img in ET.parse(xml_path).getroot().iter("image"):
        ann = ImageAnn(img.get("name"), int(img.get("width")), int(img.get("height")))
        for box in img.iter("box"):
            if box.get("label") != "plate":
                continue
            attrs = {a.get("name"): (a.text or "").strip() for a in box.iter("attribute")}
            ann.plates.append(
                PlateBox(
                    xtl=float(box.get("xtl")),
                    ytl=float(box.get("ytl")),
                    xbr=float(box.get("xbr")),
                    ybr=float(box.get("ybr")),
                    text=attrs.get("text") or None,
                    province=attrs.get("province") or None,
                    readable=attrs.get("readable", "true").lower() == "true",
                    plate_type=attrs.get("plate_type", "car") or "car",
                )
            )
        images.append(ann)
    return images


def split_of(image_name: str, val_pct: int, test_pct: int) -> str:
    info = parse_frame_name(image_name)
    group = f"{info.camera}_{info.taken_at:%Y%m%d%H}" if info else Path(image_name).stem
    bucket = int(hashlib.sha1(group.encode()).hexdigest(), 16) % 100
    if bucket < test_pct:
        return "test"
    if bucket < test_pct + val_pct:
        return "val"
    return "train"


def _crop(img: Image.Image, b: PlateBox, top: float, bottom: float) -> Image.Image:
    h = b.ybr - b.ytl
    return img.crop((round(b.xtl), round(b.ytl + h * top), round(b.xbr), round(b.ytl + h * bottom)))


def convert(
    xml_path: Path,
    images_dir: Path,
    out: Path,
    *,
    val_pct: int = 10,
    test_pct: int = 10,
    text_split: float = 0.62,
) -> dict:
    """text_split: สัดส่วนความสูงของป้ายรถยนต์ที่เป็นบรรทัดเลขทะเบียน ส่วนที่เหลือเป็นจังหวัด"""
    anns = parse_cvat(xml_path)
    coco = {s: {"images": [], "annotations": [], "categories": [{"id": 1, "name": "plate"}]} for s in SPLITS}
    ocr_rows: dict[str, list] = {s: [] for s in SPLITS}
    prov_rows: dict[str, list] = {s: [] for s in SPLITS}
    rejected: Counter[str] = Counter()
    rejected_examples: dict[str, list[str]] = {}
    ann_id = 0

    def reject(reason: str, where: str) -> None:
        rejected[reason] += 1
        rejected_examples.setdefault(reason, [])
        if len(rejected_examples[reason]) < 20:
            rejected_examples[reason].append(where)

    for image_id, ann in enumerate(anns, 1):
        split = split_of(ann.name, val_pct, test_pct)
        src = images_dir / ann.name
        if not src.exists():
            reject("image_missing", ann.name)
            continue
        coco[split]["images"].append(
            {"id": image_id, "file_name": str(src.resolve()), "width": ann.width, "height": ann.height}
        )
        img = None
        for k, b in enumerate(ann.plates):
            where = f"{ann.name}#{k}"
            w, h = b.xbr - b.xtl, b.ybr - b.ytl
            if w <= 1 or h <= 1:
                reject("box_too_small", where)
                continue
            ann_id += 1
            coco[split]["annotations"].append(
                {
                    "id": ann_id,
                    "image_id": image_id,
                    "category_id": 1,
                    "bbox": [b.xtl, b.ytl, w, h],
                    "area": w * h,
                    "iscrowd": 0,
                }
            )
            # ด้านล่างนี้เฉพาะ OCR / จังหวัด: ใช้ได้เฉพาะป้ายรถยนต์ที่อ่านออก
            if not b.readable:
                reject("unreadable", where)
                continue
            if b.plate_type != "car":
                reject(f"plate_type:{b.plate_type}", where)
                continue
            if img is None:
                img = Image.open(src).convert("RGB")
            stem = f"{Path(ann.name).stem}_{k}"

            text = clean_plate_text(b.text or "")
            if not text:
                reject("text_missing", where)
            elif any(c not in OCR_CHARSET for c in text):
                reject("text_bad_char", f"{where} {text}")
            elif not is_standard_plate(text):
                reject("text_non_standard", f"{where} {text}")
            else:
                rel = f"images/{stem}.png"
                (out / "ocr" / split / "images").mkdir(parents=True, exist_ok=True)
                _crop(img, b, 0.0, text_split).save(out / "ocr" / split / rel)
                ocr_rows[split].append((rel, text))

            province = normalize_province(b.province)
            if b.province and province is None:
                reject("province_unknown", f"{where} {b.province}")
            elif province:
                rel = f"images/{stem}.png"
                (out / "province" / split / "images").mkdir(parents=True, exist_ok=True)
                _crop(img, b, text_split, 1.0).save(out / "province" / split / rel)
                prov_rows[split].append((rel, province))

    for s in SPLITS:
        det = out / "det" / s / "annotations.json"
        det.parent.mkdir(parents=True, exist_ok=True)
        det.write_text(json.dumps(coco[s], ensure_ascii=False), encoding="utf-8")
        write_tsv(out / "ocr" / s / "labels.tsv", ocr_rows[s])
        write_tsv(out / "province" / s / "labels.tsv", prov_rows[s])

    report = {
        "source": str(xml_path),
        "counts": {
            s: {
                "images": len(coco[s]["images"]),
                "plates": len(coco[s]["annotations"]),
                "ocr": len(ocr_rows[s]),
                "province": len(prov_rows[s]),
            }
            for s in SPLITS
        },
        "rejected": dict(rejected),
        "rejected_examples": rejected_examples,
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("xml", type=Path)
    p.add_argument("--images", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--val-pct", type=int, default=10)
    p.add_argument("--test-pct", type=int, default=10)
    p.add_argument("--text-split", type=float, default=0.62)
    a = p.parse_args()
    report = convert(a.xml, a.images, a.out, val_pct=a.val_pct, test_pct=a.test_pct, text_split=a.text_split)
    print(json.dumps({"counts": report["counts"], "rejected": report["rejected"]}, ensure_ascii=False, indent=2))
    for s, c in report["counts"].items():
        if c["ocr"] == 0:
            print(f"คำเตือน: ชุด {s} ไม่มีภาพ OCR เลย ต้องเพิ่มข้อมูลจากกล้อง/ช่วงเวลาที่หลากหลายขึ้น")


if __name__ == "__main__":
    main()
