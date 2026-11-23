"""ดึงเฟรมจากคลิปที่บันทึกจากกล้อง เพื่อนำไป label ใน CVAT (ใช้ CPU)

ชื่อคลิปต้องเป็น {camera_id}_{YYYYmmddTHHMMSS}.mp4 (ตามคำสั่ง ffmpeg ใน README)
ข้ามเฟรมที่แทบไม่ต่างจากเฟรมที่เก็บล่าสุด (รถจอดนิ่ง) เพื่อไม่ให้ต้อง label ภาพซ้ำ

    python -m flock_train.extract_frames clips/*.mp4 --out frames --every 1.0
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

from flock_train.common import frame_name

CLIP_NAME = re.compile(r"^(?P<camera>[A-Za-z0-9][A-Za-z0-9.\-]*)_(?P<ts>\d{8}T\d{6})$")


def extract(clip: Path, out: Path, every_s: float, min_diff: float) -> int:
    m = CLIP_NAME.match(clip.stem)
    if not m:
        raise SystemExit(f"{clip.name}: ชื่อไฟล์ต้องเป็น <camera>_<YYYYmmddTHHMMSS>.mp4")
    camera, start = m["camera"], datetime.strptime(m["ts"], "%Y%m%dT%H%M%S")

    cap = cv2.VideoCapture(str(clip))
    if not cap.isOpened():
        raise SystemExit(f"เปิด {clip} ไม่ได้")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, round(fps * every_s))

    out.mkdir(parents=True, exist_ok=True)
    last_small: np.ndarray | None = None
    saved = idx = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            small = cv2.cvtColor(cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2GRAY).astype(np.float32)
            if last_small is None or float(np.mean(np.abs(small - last_small))) >= min_diff:
                taken = start + timedelta(seconds=idx / fps)
                cv2.imwrite(str(out / frame_name(camera, taken, idx)), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                last_small = small
                saved += 1
        idx += 1
    cap.release()
    return saved


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("clips", nargs="+", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--every", type=float, default=1.0, help="วินาทีระหว่างเฟรมที่พิจารณา")
    p.add_argument("--min-diff", type=float, default=4.0, help="ค่าต่างเฉลี่ยขั้นต่ำ (0-255) จากเฟรมก่อน")
    a = p.parse_args()
    for clip in a.clips:
        print(f"{clip.name}: {extract(clip, a.out, a.every, a.min_diff)} frames")


if __name__ == "__main__":
    main()
