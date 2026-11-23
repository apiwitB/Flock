import threading
from datetime import timedelta

import psycopg
import pytest
from conftest import make_event
from fastapi.testclient import TestClient

from flock_api import auth, linker, writer
from flock_api.app import create_app
from flock_api.topology import Topology

TOPO = Topology.from_dict(
    {
        "linker": {"settle_seconds": 0},
        "cameras": {
            "G-entry": {"role": "entry"},
            "B1-ramp-up": {"role": "internal"},
            "L2-north": {"role": "internal"},
            "G-exit": {"role": "exit"},
        },
        "links": [
            {"a": "G-entry", "b": "B1-ramp-up", "min_seconds": 5, "max_seconds": 120},
            {"a": "B1-ramp-up", "b": "L2-north", "min_seconds": 10, "max_seconds": 180, "both_ways": True},
            {"a": "B1-ramp-up", "b": "G-exit", "min_seconds": 5, "max_seconds": 120},
        ],
    }
)

CAR_A = [1.0] + [0.0] * 511
CAR_B = [0.0, 1.0] + [0.0] * 510
S = lambda n: timedelta(seconds=n)  # noqa: E731


def scenario(conn):
    """รถ A: เข้า → B1 (OCR อ่าน ข เป็น ช) → L2 (อ่านป้ายไม่ได้) → จอดนาน → ออก
    รถ B: เข้าใกล้ๆ กัน แล้วยังไม่ไปไหน"""
    events = {
        "a_entry": make_event("1กข1234", camera="G-entry", ago=S(600), embedding=CAR_A),
        "b_entry": make_event("9ฮฮ9", camera="G-entry", ago=S(590), embedding=CAR_B, color="black"),
        "a_b1": make_event("1กช1234", camera="B1-ramp-up", ago=S(570), embedding=CAR_A),
        "a_l2": make_event(None, camera="L2-north", ago=S(540), embedding=CAR_A),
        "a_exit": make_event("1กข1234", camera="G-exit", ago=S(60)),
    }
    for ev in events.values():
        writer.store(conn, ev)
    return events


def links(conn):
    return {
        str(sid): (jid, method, score)
        for sid, jid, method, score in conn.execute(
            "SELECT sighting_id, journey_id, link_method, link_score FROM sightings"
        )
    }


def test_full_journey(conn):
    ev = scenario(conn)
    counts = linker.link_pending(conn, TOPO)
    assert counts == {"new": 2, "similar_plate": 1, "guess": 1, "exact": 1}

    got = links(conn)
    a = got[str(ev["a_entry"].sighting_id)][0]
    b = got[str(ev["b_entry"].sighting_id)][0]
    assert a != b
    assert got[str(ev["a_entry"].sighting_id)] == (a, "new", None)
    assert got[str(ev["a_b1"].sighting_id)][:2] == (a, "similar_plate")
    assert got[str(ev["a_l2"].sighting_id)] == (a, "guess", pytest.approx(1.0))
    assert got[str(ev["a_exit"].sighting_id)] == (a, "exact", 1.0)

    plate, closed, span = conn.execute(
        "SELECT plate_text, closed, last_seen - first_seen FROM journeys WHERE journey_id = %s", (a,)).fetchone()
    assert (plate, closed, round(span.total_seconds())) == ("1กข1234", True, 540)
    assert conn.execute("SELECT closed FROM journeys WHERE journey_id = %s", (b,)).fetchone() == (False,)

    assert linker.link_pending(conn, TOPO) == {}  # ไม่มีอะไรค้างแล้ว


def test_new_visit_after_exit_starts_new_journey(conn):
    ev = scenario(conn)
    linker.link_pending(conn, TOPO)
    again = make_event("1กข1234", camera="G-entry", ago=S(10))
    writer.store(conn, again)
    linker.link_pending(conn, TOPO)
    got = links(conn)
    assert got[str(again.sighting_id)][1] == "new"
    assert got[str(again.sighting_id)][0] != got[str(ev["a_entry"].sighting_id)][0]


def test_better_plate_reading_updates_journey(conn):
    writer.store(conn, make_event("1กช1234", camera="G-entry", ago=S(100), plate_confidence=0.5))
    writer.store(conn, make_event("1กข1234", camera="B1-ramp-up", ago=S(80), plate_confidence=0.95))
    writer.store(conn, make_event("1กช1234", camera="L2-north", ago=S(60), plate_confidence=0.95))  # เท่ากัน: ไม่ทับ
    linker.link_pending(conn, TOPO)
    assert conn.execute("SELECT count(*), max(plate_text), max(plate_confidence) FROM journeys").fetchone() == (
        1, "1กข1234", pytest.approx(0.95))


def test_idle_journeys_are_closed(conn):
    writer.store(conn, make_event("กข1", camera="L2-north", ago=timedelta(hours=25)))
    linker.link_pending(conn, TOPO)
    assert linker.close_idle(conn, TOPO) == 1
    assert conn.execute("SELECT closed FROM journeys").fetchone() == (True,)


def test_only_one_linker_at_a_time(conn, settings):
    with psycopg.connect(settings.database_url, autocommit=True) as holder:
        holder.execute("SELECT pg_advisory_lock(%s)", (linker.LOCK_KEY,))
        with pytest.raises(SystemExit):
            linker.run(settings, TOPO, threading.Event())


def test_journey_timeline_api(conn, settings, owner_conn):
    ev = scenario(conn)
    linker.link_pending(conn, TOPO)
    jid = links(conn)[str(ev["a_entry"].sighting_id)][0]
    pw = "correct horse battery"
    auth.create_user(conn, "inv1", pw, "investigator")
    auth.create_user(conn, "viewer1", pw, "viewer")

    with TestClient(create_app(settings)) as client:
        client.post("/auth/login", json={"username": "viewer1", "password": pw})
        assert client.get(f"/journeys/{jid}").status_code == 403
        client.cookies.clear()
        client.post("/auth/login", json={"username": "inv1", "password": pw})
        body = client.get(f"/journeys/{jid}").json()
        assert client.get("/journeys/999999").status_code == 404

    assert body["plate_text"] == "1กข1234" and body["closed"] is True
    assert body["weakest_link"] == "guess"  # หน้าเว็บต้องแสดงว่าเส้นทางนี้มีช่วงที่ "เดา"
    assert [s["camera_id"] for s in body["sightings"]] == ["G-entry", "B1-ramp-up", "L2-north", "G-exit"]
    assert [s["link_method"] for s in body["sightings"]] == ["new", "similar_plate", "guess", "exact"]

    views = [q["journey_id"] for a, q in owner_conn.execute("SELECT action, query FROM audit_log") if a == "view.journey"]
    assert views == [jid, 999999]
