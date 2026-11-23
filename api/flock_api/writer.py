"""รับ Sighting event จากคิวแล้วเขียนลง Postgres

- ทำซ้ำได้ปลอดภัย: event เดิมส่งซ้ำ (redelivery) จะไม่เกิดแถวซ้ำ
- event ที่เขียนไม่ได้เพราะตัวข้อมูลเอง (schema ผิด, กล้องที่ไม่รู้จัก, เก่าเกินรอบเก็บ ฯลฯ) ถูกย้ายไป
  dead-letter stream พร้อมเหตุผล แล้ว ack เพื่อไม่ให้ค้างคิว
- ปัญหาชั่วคราว (ฐานข้อมูลล่ม) ไม่ ack ข้อความยังค้างใน pending และถูกประมวลผลใหม่เมื่อ writer เริ่มใหม่

    flock-writer
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from datetime import UTC, datetime

import psycopg
import redis
from psycopg import errors
from pydantic import ValidationError

from flock_api.config import Settings
from flock_contracts import SightingEvent, normalize_for_search
from flock_contracts.stream import DEAD_LETTER_STREAM, EVENT_FIELD, STREAM, WRITER_GROUP

log = logging.getLogger("flock.writer")

RETENTION_DAYS = 30
MAX_FUTURE_DAYS = 7
CLAIM_IDLE_MS = 60_000
DEAD_LETTER_MAXLEN = 100_000

INSERT_SQL = """
INSERT INTO sightings (
    sighting_id, observed_at, camera_id, subject_type, local_track_id,
    plate_text, plate_norm, plate_confidence, province, province_confidence,
    attributes, embedding, embedding_model, crop_path, context_path, reader_versions, schema_version
) VALUES (
    %(sighting_id)s, %(observed_at)s, %(camera_id)s, %(subject_type)s, %(local_track_id)s,
    %(plate_text)s, %(plate_norm)s, %(plate_confidence)s, %(province)s, %(province_confidence)s,
    %(attributes)s, %(embedding)s::vector, %(embedding_model)s, %(crop_path)s, %(context_path)s,
    %(reader_versions)s, %(schema_version)s
)
ON CONFLICT (sighting_id, observed_at) DO NOTHING
"""


class Rejected(Exception):
    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason


def to_row(ev: SightingEvent) -> dict:
    p = ev.plate
    return {
        "sighting_id": ev.sighting_id,
        "observed_at": ev.observed_at,
        "camera_id": ev.camera_id,
        "subject_type": ev.subject_type.value,
        "local_track_id": ev.track_id,
        "plate_text": p.text if p else None,
        "plate_norm": normalize_for_search(p.text) if p else None,
        "plate_confidence": p.confidence if p else None,
        "province": p.province if p else None,
        "province_confidence": p.province_confidence if p else None,
        "attributes": psycopg.types.json.Jsonb({k: v.model_dump() for k, v in ev.attributes.items()}),
        "embedding": "[" + ",".join(repr(x) for x in ev.embedding) + "]" if ev.embedding else None,
        "embedding_model": ev.embedding_model,
        "crop_path": ev.images.crop_path,
        "context_path": ev.images.context_path,
        "reader_versions": psycopg.types.json.Jsonb(ev.reader_versions),
        "schema_version": ev.schema_version,
    }


def check_age(ev: SightingEvent, now: datetime) -> int:
    """คืนจำนวนวันย้อนหลังที่ต้องมี partition หรือ Rejected ถ้าอยู่นอกช่วงที่รับได้"""
    days_back = (now.date() - ev.observed_at.date()).days
    if days_back >= RETENTION_DAYS:
        raise Rejected("too_old", f"observed_at {ev.observed_at.isoformat()} is outside the {RETENTION_DAYS}-day retention")
    if -days_back > MAX_FUTURE_DAYS:
        raise Rejected("clock_skew", f"observed_at {ev.observed_at.isoformat()} is in the future")
    return max(days_back, 1)


def store(conn: psycopg.Connection, ev: SightingEvent, now: datetime | None = None) -> bool:
    """คืน True ถ้าเพิ่มแถวใหม่ False ถ้ามีอยู่แล้ว"""
    days_back = check_age(ev, now or datetime.now(UTC))
    row = to_row(ev)
    for attempt in (1, 2):
        try:
            with conn.transaction():
                return conn.execute(INSERT_SQL, row).rowcount == 1
        except errors.CheckViolation as e:
            if "no partition" not in str(e) or attempt == 2:
                raise Rejected("constraint", str(e)) from e
            conn.execute("SELECT flock_ensure_partitions(%s, %s)", (days_back, MAX_FUTURE_DAYS))
        except errors.ForeignKeyViolation as e:
            raise Rejected("unknown_camera", f"camera_id {ev.camera_id!r} is not registered") from e
        except errors.DataException as e:  # เช่น มิติ embedding ไม่ตรงกับ vector(512)
            raise Rejected("bad_data", str(e)) from e
    raise AssertionError("unreachable")


def handle(conn: psycopg.Connection, r: redis.Redis, msg_id: bytes, fields: dict) -> str:
    raw = (fields or {}).get(EVENT_FIELD.encode(), b"")  # fields เป็น None ถ้าข้อความถูกตัดออกจาก stream แล้ว
    try:
        ev = SightingEvent.model_validate_json(raw)
        outcome = "stored" if store(conn, ev) else "duplicate"
    except ValidationError as e:
        outcome = dead_letter(r, msg_id, raw, "invalid", str(e))
    except Rejected as e:
        outcome = dead_letter(r, msg_id, raw, e.reason, str(e))
    r.xack(STREAM, WRITER_GROUP, msg_id)
    return outcome


def dead_letter(r: redis.Redis, msg_id: bytes, raw: bytes, reason: str, detail: str) -> str:
    log.warning("dead-letter %s: %s", reason, detail[:200])
    r.xadd(
        DEAD_LETTER_STREAM,
        {"source_id": msg_id, "reason": reason, "error": detail[:2000], EVENT_FIELD: raw},
        maxlen=DEAD_LETTER_MAXLEN,
        approximate=True,
    )
    return f"dead:{reason}"


def ensure_group(r: redis.Redis) -> None:
    try:
        r.xgroup_create(STREAM, WRITER_GROUP, id="0", mkstream=True)
    except redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


def claim_abandoned(r: redis.Redis, consumer: str) -> int:
    """รับข้อความที่ writer ตัวอื่นอ่านไปแล้วแต่ไม่ได้ ack (เช่น ตัวนั้นล้ม)"""
    claimed, start = 0, "0-0"
    while True:
        start, msgs, _ = r.xautoclaim(STREAM, WRITER_GROUP, consumer, CLAIM_IDLE_MS, start_id=start, count=100)
        claimed += len(msgs)
        if start in (b"0-0", "0-0"):
            return claimed


def run(settings: Settings, stop: threading.Event, batch: int = 100, block_ms: int = 2000) -> dict[str, int]:
    counts: dict[str, int] = {}
    r = redis.Redis.from_url(settings.queue_url)
    ensure_group(r)
    consumer = settings.writer_name
    log.info("writer %s reading %s as group %s", consumer, STREAM, WRITER_GROUP)
    if n := claim_abandoned(r, consumer):
        log.info("claimed %d abandoned messages", n)

    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        conn.execute("SELECT flock_ensure_partitions()")
        last_ensure = time.monotonic()
        read_from = "0"  # ข้อความค้างของ consumer นี้ก่อน แล้วจึงอ่านของใหม่
        while not stop.is_set():
            resp = r.xreadgroup(WRITER_GROUP, consumer, {STREAM: read_from}, count=batch,
                                block=None if read_from == "0" else block_ms)
            msgs = resp[0][1] if resp else []
            if read_from == "0" and not msgs:
                read_from = ">"
                continue
            for msg_id, fields in msgs:
                outcome = handle(conn, r, msg_id, fields)
                counts[outcome] = counts.get(outcome, 0) + 1
            if time.monotonic() - last_ensure > 3600:
                conn.execute("SELECT flock_ensure_partitions()")
                last_ensure = time.monotonic()
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    log.info("writer stopped: %s", run(Settings.from_env(), stop))


if __name__ == "__main__":
    main()
