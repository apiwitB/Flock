from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# ชื่อไฟล์เฟรมที่ extract_frames เขียน: {camera_id}_{YYYYmmddTHHMMSS}_{index}.jpg
FRAME_NAME = re.compile(r"^(?P<camera>[A-Za-z0-9][A-Za-z0-9.\-]*)_(?P<ts>\d{8}T\d{6})_(?P<idx>\d+)\.\w+$")


@dataclass(frozen=True)
class FrameInfo:
    camera: str
    taken_at: datetime


def parse_frame_name(name: str) -> FrameInfo | None:
    m = FRAME_NAME.match(Path(name).name)
    if not m:
        return None
    return FrameInfo(m["camera"], datetime.strptime(m["ts"], "%Y%m%dT%H%M%S"))


def frame_name(camera: str, taken_at: datetime, index: int) -> str:
    return f"{camera}_{taken_at:%Y%m%dT%H%M%S}_{index:06d}.jpg"


def read_tsv(path: Path) -> list[tuple[Path, str]]:
    """อ่านไฟล์ labels.tsv (path<TAB>label) คืน path แบบเต็ม"""
    rows = []
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if row:
                rows.append((path.parent / row[0], row[1]))
    return rows


def write_tsv(path: Path, rows: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", quoting=csv.QUOTE_NONE, lineterminator="\n")
        w.writerows(rows)
