"""ตัวช่วยเรื่องข้อความบนป้ายทะเบียน (บรรทัดเลขทะเบียน ไม่รวมจังหวัด)

ใช้ร่วมกันระหว่าง training (ชุดตัวอักษรของ OCR), linker และ search API

CONFUSABLE_PAIRS เป็นค่าตั้งต้นจากการเดา ต้องแทนด้วย confusion matrix ที่วัดจาก OCR จริง
(training/tools/eval_ocr.py เขียนไฟล์ confusion_pairs.json ออกมาให้)
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

THAI_CONSONANTS = "กขฃคฅฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรลวศษสหฬอฮ"
DIGITS = "0123456789"

# ชุดตัวอักษรที่ OCR ต้องอ่านได้ ลำดับนี้ใช้เป็น vocabulary ของโมเดล ห้ามสลับ
OCR_CHARSET = THAI_CONSONANTS + DIGITS

# ป้ายรถส่วนบุคคลมาตรฐาน: เลขนำหน้า (ไม่บังคับ) + พยัญชนะ 1-2 ตัว + เลข 1-4 หลัก
_STANDARD_PLATE = re.compile(rf"^[1-9]?[{THAI_CONSONANTS}]{{1,2}}[1-9][0-9]{{0,3}}$")

_STRIP = re.compile(r"[\s\-.·]")

CONFUSABLE_PAIRS: tuple[tuple[str, str], ...] = (
    ("ข", "ช"), ("ช", "ซ"), ("ด", "ต"), ("ค", "ด"), ("ถ", "ภ"), ("ศ", "ส"),
    ("บ", "ป"), ("ฎ", "ฏ"), ("ผ", "ฝ"), ("พ", "ฟ"), ("ท", "ฑ"), ("อ", "ฮ"),
    ("ม", "ฆ"), ("ร", "ธ"),
    ("0", "8"), ("3", "8"), ("6", "8"), ("5", "6"), ("1", "7"),
)

CONFUSABLE_COST = 0.4


def clean_plate_text(text: str) -> str:
    """ตัดช่องว่าง ขีด จุด และ normalize Unicode"""
    return _STRIP.sub("", unicodedata.normalize("NFC", text))


def is_standard_plate(text: str) -> bool:
    return bool(_STANDARD_PLATE.match(clean_plate_text(text)))


def _build_groups(pairs: Iterable[tuple[str, str]]) -> dict[str, str]:
    """union-find: แต่ละตัวอักษรชี้ไปที่ตัวแทนของกลุ่ม (ตัวที่มาก่อนใน OCR_CHARSET)"""
    parent: dict[str, str] = {}

    def find(c: str) -> str:
        parent.setdefault(c, c)
        while parent[c] != c:
            parent[c] = parent[parent[c]]
            c = parent[c]
        return c

    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            keep, drop = sorted((ra, rb), key=OCR_CHARSET.index)
            parent[drop] = keep
    return {c: find(c) for c in list(parent)}


_GROUP_OF = _build_groups(CONFUSABLE_PAIRS)
_CONFUSABLE = frozenset(frozenset(p) for p in CONFUSABLE_PAIRS)


def normalize_for_search(text: str) -> str:
    """ยุบตัวอักษรที่หน้าตาคล้ายกันให้เป็นตัวเดียว ใช้สำหรับดึงผู้สมัครด้วย pg_trgm
    แล้วค่อยจัดอันดับด้วย plate_distance"""
    return "".join(_GROUP_OF.get(c, c) for c in clean_plate_text(text))


def _sub_cost(a: str, b: str) -> float:
    if a == b:
        return 0.0
    if frozenset((a, b)) in _CONFUSABLE:
        return CONFUSABLE_COST
    return 1.0


def plate_distance(a: str, b: str) -> float:
    """Levenshtein ที่การแทนตัวอักษรหน้าตาคล้ายกันมีต้นทุนต่ำกว่า"""
    a, b = clean_plate_text(a), clean_plate_text(b)
    prev = [float(j) for j in range(len(b) + 1)]
    for i, ca in enumerate(a, 1):
        cur = [float(i)]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + _sub_cost(ca, cb)))
        prev = cur
    return prev[-1]
