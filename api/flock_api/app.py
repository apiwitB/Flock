"""Search API

สิทธิ์:
  viewer        ดูรายการรถตามกล้อง/เวลา/สี/ประเภท
  investigator  + ค้นด้วยเลขป้าย และเปิดดูภาพ
  admin         + จัดการผู้ใช้ (ยังทำผ่าน CLI: flock-users)

ทุกคำค้นและการเปิดภาพถูกบันทึกใน audit_log ใน transaction เดียวกับการค้น

    uvicorn flock_api.app:app
"""

# ไม่ใช้ `from __future__ import annotations` ในไฟล์นี้: FastAPI ต้องเห็น type จริงของ dependency
# ที่ประกาศไว้ภายใน create_app

import ipaddress
import json
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from psycopg_pool import ConnectionPool
from pydantic import AwareDatetime, BaseModel, Field

from flock_api import auth, search
from flock_api.config import Settings
from flock_contracts import normalize_province

SESSION_COOKIE = "flock_session"
MAX_WINDOW = timedelta(days=31)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    username: str
    role: str


class SightingOut(BaseModel):
    sighting_id: UUID
    observed_at: datetime
    camera_id: str
    subject_type: str
    local_track_id: str
    plate_text: str | None
    plate_confidence: float | None
    province: str | None
    province_confidence: float | None
    attributes: dict[str, Any]
    journey_id: int | None
    link_method: str | None
    link_score: float | None
    crop_url: str
    context_url: str


class PlateMatchOut(SightingOut):
    match: Literal["exact", "similar", "partial"]
    distance: float


class CameraOut(BaseModel):
    camera_id: str
    name: str
    location: str | None


class JourneyOut(BaseModel):
    journey_id: int
    subject_type: str
    first_seen: datetime
    last_seen: datetime
    plate_text: str | None
    province: str | None
    plate_confidence: float | None
    closed: bool
    # ระดับความมั่นใจต่ำสุดของการต่อในเส้นทางนี้: exact > similar_plate > guess
    weakest_link: Literal["exact", "similar_plate", "guess"] | None
    sightings: list[SightingOut]


_LINK_STRENGTH = {"exact": 0, "similar_plate": 1, "guess": 2}


def _client_ip(request: Request) -> str | None:
    """IP ของผู้เรียก หรือ None ถ้าไม่ใช่ IP (เช่น unix socket)

    หลัง Caddy: uvicorn รันด้วย --proxy-headers --forwarded-allow-ips=<IP ของ Caddy> (ดู deploy/docker-compose.yml)
    ProxyHeadersMiddleware ของ uvicorn จะเขียน request.client.host ใหม่เป็น IP จาก X-Forwarded-For
    เฉพาะเมื่อ peer เป็น IP ที่เชื่อถือ ที่นี่จึงอ่าน request.client.host อย่างเดียว ห้ามอ่าน header เอง"""
    host = request.client.host if request.client else None
    try:
        return str(ipaddress.ip_address(host)) if host else None
    except ValueError:
        return None


def _out(row: dict, model: type[BaseModel]) -> BaseModel:
    sid = row["sighting_id"]
    return model(**row, crop_url=f"/sightings/{sid}/image/crop", context_url=f"/sightings/{sid}/image/context")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pool = ConnectionPool(settings.database_url, min_size=1, max_size=10, open=True)
        app.state.pool = pool
        try:
            yield
        finally:
            pool.close()

    app = FastAPI(title="Flock search", lifespan=lifespan)

    def db(request: Request) -> Iterator[psycopg.Connection]:
        # commit เมื่อจบ request สำเร็จ, rollback เมื่อเกิด exception
        with request.app.state.pool.connection() as conn:
            yield conn

    Conn = Annotated[psycopg.Connection, Depends(db)]

    def current_user(request: Request, conn: Conn) -> auth.User:
        token = request.cookies.get(SESSION_COOKIE)
        user = auth.user_for_token(conn, token) if token else None
        if user is None:
            raise HTTPException(401, "not signed in")
        return user

    def role(minimum: str):
        def check(user: Annotated[auth.User, Depends(current_user)]) -> auth.User:
            if not user.has_role(minimum):
                raise HTTPException(403, f"requires role {minimum}")
            return user
        return check

    Viewer = Annotated[auth.User, Depends(role("viewer"))]
    Investigator = Annotated[auth.User, Depends(role("investigator"))]

    def audit(conn: psycopg.Connection, request: Request, user_id: int | None, action: str,
              query: dict, result_count: int | None) -> None:
        conn.execute(
            "INSERT INTO audit_log (user_id, action, query, result_count, client_ip) VALUES (%s, %s, %s, %s, %s)",
            (user_id, action, json.dumps(query, ensure_ascii=False, default=str), result_count,
             _client_ip(request)),
        )

    def window(start: datetime | None, end: datetime | None) -> search.TimeWindow:
        end = end or datetime.now(UTC)
        start = start or end - timedelta(days=1)
        if start >= end:
            raise HTTPException(422, "'from' must be before 'to'")
        if end - start > MAX_WINDOW:
            raise HTTPException(422, f"time window must be at most {MAX_WINDOW.days} days")
        return search.TimeWindow(start, end)

    From = Annotated[AwareDatetime | None, Query(alias="from")]
    To = Annotated[AwareDatetime | None, Query(alias="to")]
    Limit = Annotated[int, Query(ge=1, le=500)]

    # --- auth -------------------------------------------------------------------
    @app.post("/auth/login", response_model=UserOut)
    def login(body: LoginIn, request: Request, response: Response, conn: Conn):
        result = auth.login(conn, body.username, body.password, settings.session_ttl)
        if result is None:
            audit(conn, request, None, "auth.login_failed", {"username": body.username}, None)
            conn.commit()  # บันทึกความพยายามแม้ตอบ 401
            raise HTTPException(401, "invalid username or password")
        token, user = result
        audit(conn, request, user.user_id, "auth.login", {}, None)
        response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=settings.cookie_secure, samesite="strict",
                            max_age=int(settings.session_ttl.total_seconds()))
        return UserOut(username=user.username, role=user.role)

    @app.post("/auth/logout", status_code=204)
    def logout(request: Request, response: Response, conn: Conn):
        if token := request.cookies.get(SESSION_COOKIE):
            auth.logout(conn, token)
        response.delete_cookie(SESSION_COOKIE)

    @app.get("/auth/me", response_model=UserOut)
    def me(user: Viewer):
        return UserOut(username=user.username, role=user.role)

    # --- cameras ----------------------------------------------------------------
    @app.get("/cameras", response_model=list[CameraOut])
    def list_cameras(conn: Conn, user: Viewer):
        # รายชื่อกล้องไม่ใช่ข้อมูลส่วนบุคคล จึงไม่บันทึก audit_log
        return search.cameras(conn)

    # --- search -----------------------------------------------------------------
    @app.get("/search/plates", response_model=list[PlateMatchOut])
    def search_plates(
        request: Request, conn: Conn, user: Investigator,
        q: Annotated[str, Query(min_length=1, max_length=16)],
        start: From = None, end: To = None,
        camera_id: str | None = None, province: str | None = None,
        max_distance: Annotated[float, Query(ge=0, le=3)] = 2.0,
        limit: Limit = 100,
    ):
        w = window(start, end)
        prov = None
        if province:
            prov = normalize_province(province)
            if prov is None:
                raise HTTPException(422, f"unknown province: {province}")
        rows = search.search_plates(conn, q, w, camera_id=camera_id, province=prov,
                                    max_distance=max_distance, limit=limit)
        audit(conn, request, user.user_id, "search.plate",
              {"q": q, "from": w.start, "to": w.end, "camera_id": camera_id, "province": prov,
               "max_distance": max_distance}, len(rows))
        return [_out(r, PlateMatchOut) for r in rows]

    @app.get("/sightings", response_model=list[SightingOut])
    def list_sightings(
        request: Request, conn: Conn, user: Viewer,
        start: From = None, end: To = None,
        camera_id: str | None = None, color: str | None = None, vehicle_type: str | None = None,
        limit: Limit = 100,
    ):
        w = window(start, end)
        rows = search.browse(conn, w, camera_id=camera_id, color=color, vehicle_type=vehicle_type, limit=limit)
        audit(conn, request, user.user_id, "search.browse",
              {"from": w.start, "to": w.end, "camera_id": camera_id, "color": color,
               "vehicle_type": vehicle_type}, len(rows))
        return [_out(r, SightingOut) for r in rows]

    @app.get("/journeys/{journey_id}", response_model=JourneyOut)
    def get_journey(journey_id: int, request: Request, conn: Conn, user: Investigator):
        j = search.journey(conn, journey_id)
        audit(conn, request, user.user_id, "view.journey", {"journey_id": journey_id}, 1 if j else 0)
        conn.commit()
        if j is None:
            raise HTTPException(404, "journey not found")
        links = [s["link_method"] for s in j["sightings"] if s["link_method"] in _LINK_STRENGTH]
        weakest = max(links, key=_LINK_STRENGTH.__getitem__) if links else None
        return JourneyOut(**{k: v for k, v in j.items() if k != "sightings"}, weakest_link=weakest,
                          sightings=[_out(s, SightingOut) for s in j["sightings"]])

    @app.get("/sightings/{sighting_id}/image/{kind}")
    def image(sighting_id: UUID, kind: Literal["crop", "context"], request: Request, conn: Conn, user: Investigator):
        rel = search.image_path(conn, sighting_id, kind)
        audit(conn, request, user.user_id, "view.image", {"sighting_id": sighting_id, "kind": kind},
              1 if rel else 0)
        conn.commit()  # บันทึกทุกความพยายามเปิดภาพ รวมถึงที่ตอบ 404 (เช่น เดา id หรือ path)
        if rel is None:
            raise HTTPException(404, "sighting not found")
        root = settings.image_root.resolve()
        path = (root / rel).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(404, "image not found")
        return FileResponse(path, headers={"Cache-Control": "private, no-store"})

    return app


def __getattr__(name: str):
    # ให้ `uvicorn flock_api.app:app` สร้างแอปจาก environment ตอนเรียกใช้ ไม่ใช่ตอน import
    if name == "app":
        return create_app()
    raise AttributeError(name)
