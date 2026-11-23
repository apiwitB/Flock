"""ข้อมูลจำลองสำหรับลองหน้าเว็บบนเครื่องพัฒนา (ห้ามรันกับเครื่องจริง)

ส่ง event ผ่านคิวจริง ให้ writer และ linker ประมวลผลตามปกติ แล้วสร้างผู้ใช้ทดลอง
รหัสผ่านของผู้ใช้ทดลองถูกเขียนลง /out/dev-users.local (ไม่พิมพ์ออกหน้าจอ)

    cd deploy
    docker compose run --rm --no-deps -v images:/data/images -v ../scripts:/s:ro -v ./:/out \
        -e FLOCK_OWNER_DATABASE_URL=postgresql://flock_owner:<pw>@db:5432/flock --entrypoint python api /s/seed_demo.py
"""

import os
import secrets
import struct
import uuid
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import redis

from flock_api import auth
from flock_contracts import SightingEvent
from flock_contracts.stream import publish

CAMERAS = {
    "G-entry": ("ทางเข้า ชั้น G", "ชั้น G ฝั่งถนนใหญ่"),
    "B1-ramp-up": ("ทางลาดขึ้น B1", "ชั้น B1"),
    "L2-north": ("ชั้น 2 ฝั่งเหนือ", "ชั้น 2"),
    "G-exit": ("ทางออก ชั้น G", "ชั้น G ฝั่งซอย"),
}
COLORS = {"white": (235, 235, 235), "black": (30, 30, 35), "red": (190, 40, 40), "silver": (170, 175, 180)}
IMAGE_ROOT = Path(os.environ.get("FLOCK_IMAGE_ROOT", "/data/images"))


def png(width: int, height: int, rgb: tuple[int, int, int], band: tuple[int, int, int]) -> bytes:
    """ภาพตัวอย่างแบบง่าย: สีรถ + แถบป้ายสีขาวตรงกลาง (ไม่ใช่ภาพจริง)"""
    rows = []
    for y in range(height):
        row = bytearray(b"\x00")
        for x in range(width):
            in_plate = height * 0.6 < y < height * 0.8 and width * 0.3 < x < width * 0.7
            row += bytes(band if in_plate else rgb)
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def embedding(seed: int) -> list[float]:
    v = [0.0] * 512
    v[seed] = 1.0
    return v


def event(camera, at, plate, conf, color, vtype, emb):
    sid = uuid.uuid4()
    day = at.strftime("%Y-%m-%d")
    paths = {k: f"{day}/{camera}/{sid}_{k}.png" for k in ("crop", "context")}
    for kind, (w, h) in (("crop", (160, 120)), ("context", (480, 270))):
        f = IMAGE_ROOT / paths[kind]
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(png(w, h, COLORS[color], (250, 250, 250) if plate else COLORS[color]))
    return SightingEvent.model_validate({
        "sighting_id": sid, "camera_id": camera, "observed_at": at, "subject_type": "vehicle",
        "track_id": f"{camera}.{secrets.randbelow(10000)}",
        "plate": {"text": plate, "confidence": conf, "province": "กรุงเทพมหานคร", "province_confidence": 0.9}
        if plate else None,
        "attributes": {"color": {"value": color, "confidence": 0.85}, "vehicle_type": {"value": vtype, "confidence": 0.8}},
        "embedding": emb, "embedding_model": "demo" if emb else None,
        "images": {"crop_path": paths["crop"], "context_path": paths["context"]},
        "reader_versions": {"plate": "demo", "attr": "demo"},
    })


def main() -> None:
    with psycopg.connect(os.environ["FLOCK_OWNER_DATABASE_URL"], autocommit=True) as owner:
        for cid, (name, loc) in CAMERAS.items():
            owner.execute("INSERT INTO cameras (camera_id, name, location) VALUES (%s, %s, %s) "
                          "ON CONFLICT (camera_id) DO UPDATE SET name = excluded.name, location = excluded.location",
                          (cid, name, loc))

    now = datetime.now(UTC)
    m = lambda n: now - timedelta(minutes=n)  # noqa: E731
    s = timedelta(seconds=1)
    events = [
        # รถ 1: เข้า → B1 (OCR อ่าน ข เป็น ช) → L2 (อ่านป้ายไม่ได้ ใช้ embedding) → จอด → ออก
        event("G-entry", m(180), "1กข1234", 0.94, "white", "sedan", embedding(0)),
        event("B1-ramp-up", m(180) + 30 * s, "1กช1234", 0.71, "white", "sedan", embedding(0)),
        event("L2-north", m(180) + 70 * s, None, 0, "white", "sedan", embedding(0)),
        event("G-exit", m(20), "1กข1234", 0.92, "white", "sedan", None),
        # รถ 2: ป้ายชัดทุกจุด เข้าแล้วออก
        event("G-entry", m(120), "2กข5678", 0.97, "red", "pickup", embedding(1)),
        event("B1-ramp-up", m(120) + 25 * s, "2กข5678", 0.95, "red", "pickup", embedding(1)),
        event("G-exit", m(60), "2กข5678", 0.96, "red", "pickup", None),
        # รถ 3: ยังจอดอยู่
        event("G-entry", m(90), "9ฮฮ9", 0.88, "black", "suv", embedding(2)),
        event("B1-ramp-up", m(90) + 40 * s, "9ฮฮ9", 0.83, "black", "suv", embedding(2)),
        # รถ 4: ป้ายอ่านไม่ได้เลย
        event("G-entry", m(45), None, 0, "silver", "sedan", embedding(3)),
    ]
    r = redis.Redis.from_url(os.environ["FLOCK_QUEUE_URL"])
    for ev in sorted(events, key=lambda e: e.observed_at):
        publish(r, ev)

    lines = []
    with psycopg.connect(os.environ["FLOCK_DATABASE_URL"], autocommit=True) as app:
        for username, role in (("demo-admin", "admin"), ("demo-inv", "investigator"), ("demo-view", "viewer")):
            if app.execute("SELECT 1 FROM users WHERE username = %s", (username,)).fetchone():
                continue
            pw = secrets.token_urlsafe(15)
            auth.create_user(app, username, pw, role)
            lines.append(f"{username}\t{role}\t{pw}")
    if lines:
        out = Path("/out/dev-users.local")
        with out.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    print(f"published {len(events)} events; new users: {len(lines)} (see deploy/dev-users.local)")


if __name__ == "__main__":
    main()
