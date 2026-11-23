import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import make_event
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from flock_api import auth, writer
from flock_api.app import SESSION_COOKIE, create_app

PASSWORD = "correct horse battery"


@pytest.fixture
def client(settings, conn):
    auth.create_user(conn, "viewer1", PASSWORD, "viewer")
    auth.create_user(conn, "inv1", PASSWORD, "investigator")
    with TestClient(create_app(settings)) as c:
        yield c


def sign_in(client, username):
    resp = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return resp


def audit_rows(owner_conn):
    return owner_conn.execute("SELECT action, query, result_count, user_id FROM audit_log ORDER BY audit_id").fetchall()


def seed(conn, *plates_and_kw):
    for plate, kw in plates_and_kw:
        writer.store(conn, make_event(plate, **kw))


def test_requires_login(client):
    assert client.get("/sightings").status_code == 401
    assert client.get("/search/plates", params={"q": "1"}).status_code == 401


def test_wrong_password_is_rejected_and_audited(client, owner_conn):
    resp = client.post("/auth/login", json={"username": "inv1", "password": "wrong password!!"})
    assert resp.status_code == 401
    resp = client.post("/auth/login", json={"username": "nobody", "password": "wrong password!!"})
    assert resp.status_code == 401
    assert [(a, q) for a, q, _, _ in audit_rows(owner_conn)] == [
        ("auth.login_failed", {"username": "inv1"}),
        ("auth.login_failed", {"username": "nobody"}),
    ]


def test_session_cookie_flags(client):
    cookie = sign_in(client, "inv1").headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie


def test_viewer_can_browse_but_not_search_plates(client, conn):
    seed(conn, ("1กข1234", {}), ("2กข5678", {"color": "red", "camera": "L2-north"}))
    sign_in(client, "viewer1")
    assert client.get("/search/plates", params={"q": "1กข1234"}).status_code == 403

    rows = client.get("/sightings").json()
    assert len(rows) == 2
    rows = client.get("/sightings", params={"color": "red"}).json()
    assert [r["plate_text"] for r in rows] == ["2กข5678"]
    rows = client.get("/sightings", params={"camera_id": "B1-ramp-up"}).json()
    assert [r["plate_text"] for r in rows] == ["1กข1234"]


def test_plate_search_ranks_exact_then_similar_then_partial(client, conn, owner_conn):
    seed(
        conn,
        ("1กข1234", {"ago": timedelta(minutes=30)}),
        ("1กช1234", {"ago": timedelta(minutes=20), "camera": "L2-north"}),  # OCR อ่าน ข เป็น ช
        ("1กข1284", {"ago": timedelta(minutes=15)}),                        # 3 เป็น 8
        ("9ฮฮ1234", {"ago": timedelta(minutes=10)}),
        ("2กข5678", {"ago": timedelta(minutes=5)}),
        ("1กข1234", {"ago": timedelta(days=3)}),                            # นอกช่วงเวลาเริ่มต้น 24 ชม.
    )
    sign_in(client, "inv1")
    rows = client.get("/search/plates", params={"q": "1กข 1234"}).json()
    assert (rows[0]["plate_text"], rows[0]["match"]) == ("1กข1234", "exact")
    # ข/ช และ 3/8 เป็นคู่คล้ายกันทั้งคู่ ระยะเท่ากัน จึงเรียงคันที่เห็นล่าสุดก่อน
    assert [(r["plate_text"], r["match"], r["distance"]) for r in rows[1:]] == [
        ("1กข1284", "similar", pytest.approx(0.4)),
        ("1กช1234", "similar", pytest.approx(0.4)),
    ]

    rows = client.get("/search/plates", params={"q": "1234"}).json()
    # ค้นบางส่วนก็ทนการอ่าน 3/8 สลับกัน จึงเจอ 1กข1284 ด้วย
    assert {r["plate_text"] for r in rows} == {"1กข1234", "1กช1234", "1กข1284", "9ฮฮ1234"}
    assert {r["match"] for r in rows} == {"partial"}

    week = {"from": (datetime.now(UTC) - timedelta(days=7)).isoformat(), "to": datetime.now(UTC).isoformat()}
    rows = client.get("/search/plates", params={"q": "1กข1234", **week}).json()
    assert [r["match"] for r in rows].count("exact") == 2

    logged = [(a, q["q"], n) for a, q, n, uid in audit_rows(owner_conn) if a == "search.plate"]
    assert logged == [("search.plate", "1กข 1234", 3), ("search.plate", "1234", 4), ("search.plate", "1กข1234", 4)]


def test_search_filters_and_validation(client, conn):
    seed(conn, ("1กข1234", {}), ("1กข1234", {"camera": "L2-north"}))
    sign_in(client, "inv1")
    rows = client.get("/search/plates", params={"q": "1กข1234", "camera_id": "L2-north"}).json()
    assert [r["camera_id"] for r in rows] == ["L2-north"]
    assert client.get("/search/plates", params={"q": "1กข1234", "province": "กทม"}).status_code == 200
    assert client.get("/search/plates", params={"q": "1กข1234", "province": "ไม่มี"}).status_code == 422

    now = datetime.now(UTC)
    too_long = {"from": (now - timedelta(days=40)).isoformat(), "to": now.isoformat()}
    assert client.get("/search/plates", params={"q": "1", **too_long}).status_code == 422
    naive = {"from": "2026-11-23T08:00:00", "to": now.isoformat()}
    assert client.get("/search/plates", params={"q": "1", **naive}).status_code == 422
    backwards = {"from": now.isoformat(), "to": (now - timedelta(hours=1)).isoformat()}
    assert client.get("/search/plates", params={"q": "1", **backwards}).status_code == 422


def test_image_access(client, conn, settings, owner_conn):
    good = make_event(crop_path="2026-11-23/B1-ramp-up/a_crop.jpg")
    evil = make_event(crop_path="../../../etc/passwd")
    writer.store(conn, good)
    writer.store(conn, evil)
    img = settings.image_root / "2026-11-23/B1-ramp-up/a_crop.jpg"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"\xff\xd8fake-jpeg")

    sign_in(client, "viewer1")
    assert client.get(f"/sightings/{good.sighting_id}/image/crop").status_code == 403

    client.cookies.clear()
    sign_in(client, "inv1")
    resp = client.get(f"/sightings/{good.sighting_id}/image/crop")
    assert resp.status_code == 200 and resp.content == b"\xff\xd8fake-jpeg"
    assert "no-store" in resp.headers["cache-control"]
    assert client.get(f"/sightings/{evil.sighting_id}/image/crop").status_code == 404
    assert client.get(f"/sightings/{good.sighting_id}/image/context").status_code == 404  # ไม่มีไฟล์
    assert client.get(f"/sightings/{good.sighting_id}/image/other").status_code == 422

    views = [(q["sighting_id"], n) for a, q, n, _ in audit_rows(owner_conn) if a == "view.image"]
    assert views[0] == (str(good.sighting_id), 1)
    assert len(views) == 3  # viewer ถูกปฏิเสธก่อนถึงขั้นบันทึก, 'other' ไม่ผ่าน validation


def test_logout_invalidates_session(client):
    sign_in(client, "inv1")
    token = client.cookies.get(SESSION_COOKIE)
    assert client.get("/auth/me").json() == {"username": "inv1", "role": "investigator"}
    assert client.post("/auth/logout").status_code == 204
    client.cookies.set(SESSION_COOKIE, token)  # ใช้ token เดิมซ้ำไม่ได้
    assert client.get("/auth/me").status_code == 401


def test_disabled_user_loses_access(client, conn):
    sign_in(client, "inv1")
    conn.execute("UPDATE users SET active = false WHERE username = 'inv1'")
    assert client.get("/auth/me").status_code == 401
    assert client.post("/auth/login", json={"username": "inv1", "password": PASSWORD}).status_code == 401


def test_short_password_rejected(conn):
    with pytest.raises(ValueError):
        auth.create_user(conn, "x", "short", "viewer")


def test_cameras_lists_active_only(client, owner_conn):
    assert client.get("/cameras").status_code == 401
    owner_conn.execute("UPDATE cameras SET location = 'ชั้น B1 ทางขึ้น' WHERE camera_id = 'B1-ramp-up'")
    owner_conn.execute("INSERT INTO cameras (camera_id, name, active) VALUES ('A-old', 'old', false)")
    sign_in(client, "viewer1")
    resp = client.get("/cameras")
    assert resp.status_code == 200
    assert resp.json() == [
        {"camera_id": "B1-ramp-up", "name": "B1-ramp-up", "location": "ชั้น B1 ทางขึ้น"},
        {"camera_id": "G-entry", "name": "G-entry", "location": None},
        {"camera_id": "G-exit", "name": "G-exit", "location": None},
        {"camera_id": "L2-north", "name": "L2-north", "location": None},
    ]
    # ไม่ใช่ข้อมูลส่วนบุคคล จึงไม่บันทึก audit (มีแค่ auth.login)
    assert [a for a, *_ in audit_rows(owner_conn)] == ["auth.login"]


CADDY_IP = "172.31.250.10"


def _audited_ips(owner_conn):
    return [r[0] for r in owner_conn.execute("SELECT host(client_ip) FROM audit_log ORDER BY audit_id")]


def test_client_ip_from_trusted_proxy_only(settings, owner_conn):
    """จำลองสิ่งที่ uvicorn --proxy-headers --forwarded-allow-ips=<Caddy> ทำ: ห่อแอปด้วย ProxyHeadersMiddleware
    แล้วตรวจว่า audit_log.client_ip เป็น IP จาก X-Forwarded-For เฉพาะเมื่อ peer คือ Caddy"""
    app = ProxyHeadersMiddleware(create_app(settings), trusted_hosts=[CADDY_IP])
    bad = {"username": "nobody", "password": "wrong password!!"}
    xff = {"X-Forwarded-For": "203.0.113.7"}

    with TestClient(app, client=(CADDY_IP, 40000)) as via_caddy:
        assert via_caddy.post("/auth/login", json=bad, headers=xff).status_code == 401
        assert via_caddy.post("/auth/login", json=bad).status_code == 401  # ไม่มี header: ใช้ IP ของ peer
    with TestClient(app, client=("10.9.8.7", 40000)) as direct:
        # ยิงตรงเข้า api (ไม่ผ่าน Caddy) ปลอม X-Forwarded-For ไม่ได้
        assert direct.post("/auth/login", json=bad, headers=xff).status_code == 401

    assert _audited_ips(owner_conn) == ["203.0.113.7", CADDY_IP, "10.9.8.7"]


def test_compose_trusts_only_caddy_ip():
    """IP ใน --forwarded-allow-ips ของ api ต้องตรงกับ ipv4_address ของ Caddy และอยู่ใน subnet ของ edge"""
    compose = Path("/app/deploy/docker-compose.yml")
    if not compose.exists():
        pytest.skip("ไม่ได้ mount deploy/")
    text = compose.read_text(encoding="utf-8")
    allow = re.findall(r'"--forwarded-allow-ips",\s*"([^"]+)"', text)
    caddy = re.findall(r"ipv4_address:\s*([0-9.]+)", text)
    assert allow == [CADDY_IP] and caddy == [CADDY_IP]
    assert "--proxy-headers" in text
    assert "subnet: 172.31.250.0/24" in text
