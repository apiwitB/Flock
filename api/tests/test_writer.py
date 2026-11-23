import threading
import time
from datetime import timedelta

from conftest import make_event

from flock_api import writer
from flock_contracts.stream import DEAD_LETTER_STREAM, EVENT_FIELD, STREAM, WRITER_GROUP, publish


def handle_one(conn, r, payload: bytes | str) -> str:
    writer.ensure_group(r)
    r.xadd(STREAM, {EVENT_FIELD: payload})
    (_, msgs), = r.xreadgroup(WRITER_GROUP, "t", {STREAM: ">"}, count=1)
    msg_id, fields = msgs[0]
    return writer.handle(conn, r, msg_id, fields)


def pending(r) -> int:
    return r.xpending(STREAM, WRITER_GROUP)["pending"]


def test_store_valid_event(conn, r):
    ev = make_event("1กข 1234", embedding=[0.5] * 512)
    assert handle_one(conn, r, ev.model_dump_json()) == "stored"
    row = conn.execute(
        "SELECT plate_text, plate_norm, province, attributes->'color'->>'value', vector_dims(embedding) FROM sightings"
    ).fetchone()
    assert row == ("1กข1234", "1กข1204", "กรุงเทพมหานคร", "white", 512)
    assert pending(r) == 0


def test_redelivered_event_is_not_duplicated(conn, r):
    payload = make_event().model_dump_json()
    assert handle_one(conn, r, payload) == "stored"
    assert handle_one(conn, r, payload) == "duplicate"
    assert conn.execute("SELECT count(*) FROM sightings").fetchone()[0] == 1


def test_event_without_plate(conn, r):
    assert handle_one(conn, r, make_event(None).model_dump_json()) == "stored"
    assert conn.execute("SELECT plate_text, plate_norm FROM sightings").fetchone() == (None, None)


def test_rejections_go_to_dead_letter_and_are_acked(conn, r):
    cases = {
        "dead:invalid": b"{not json",
        "dead:unknown_camera": make_event(camera="nowhere").model_dump_json(),
        "dead:too_old": make_event(ago=timedelta(days=35)).model_dump_json(),
        "dead:clock_skew": make_event(ago=-timedelta(days=10)).model_dump_json(),
        "dead:bad_data": make_event(embedding=[0.1, 0.2, 0.3]).model_dump_json(),
    }
    for expected, payload in cases.items():
        assert handle_one(conn, r, payload) == expected
    assert pending(r) == 0
    assert conn.execute("SELECT count(*) FROM sightings").fetchone()[0] == 0
    reasons = [f[b"reason"].decode() for _, f in r.xrange(DEAD_LETTER_STREAM)]
    assert reasons == [k.removeprefix("dead:") for k in cases]


def test_late_event_creates_missing_partition(conn, r):
    # partition ตั้งต้นมีแค่ย้อนหลัง 1 วัน: event ที่มาช้า 5 วันต้องสร้าง partition ให้เอง
    assert handle_one(conn, r, make_event(ago=timedelta(days=5)).model_dump_json()) == "stored"


def test_run_processes_pending_then_new_messages(conn, r, settings):
    writer.ensure_group(r)
    # ข้อความที่ writer ชื่อเดียวกันอ่านไปแล้วแต่ล้มก่อน ack
    publish(r, make_event("กข1"))
    r.xreadgroup(WRITER_GROUP, settings.writer_name, {STREAM: ">"}, count=1)
    assert pending(r) == 1
    publish(r, make_event("กข2"))
    publish(r, make_event("กข3"))

    stop = threading.Event()
    result: dict = {}
    t = threading.Thread(target=lambda: result.update(writer.run(settings, stop, block_ms=200)))
    t.start()
    deadline = time.monotonic() + 10
    while conn.execute("SELECT count(*) FROM sightings").fetchone()[0] < 3 and time.monotonic() < deadline:
        time.sleep(0.05)
    stop.set()
    t.join(5)

    assert sorted(x for (x,) in conn.execute("SELECT plate_text FROM sightings")) == ["กข1", "กข2", "กข3"]
    assert result == {"stored": 3}
    assert pending(r) == 0
