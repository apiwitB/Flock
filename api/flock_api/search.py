"""คำค้นในฐานข้อมูล แยกจาก HTTP เพื่อทดสอบได้ตรงๆ"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from flock_contracts import clean_plate_text, normalize_for_search, plate_distance

COLUMNS = """sighting_id, observed_at, camera_id, subject_type, local_track_id,
             plate_text, plate_confidence, province, province_confidence, attributes,
             journey_id, link_method, link_score"""

MIN_TRIGRAM_SIMILARITY = 0.2
MAX_CANDIDATES = 1000


@dataclass(frozen=True)
class TimeWindow:
    start: datetime
    end: datetime


def _filters(window: TimeWindow, camera_id: str | None, province: str | None) -> tuple[str, list[Any]]:
    sql = ["observed_at >= %s", "observed_at < %s"]
    args: list[Any] = [window.start, window.end]
    if camera_id:
        sql.append("camera_id = %s")
        args.append(camera_id)
    if province:
        sql.append("province = %s")
        args.append(province)
    return " AND ".join(sql), args


def search_plates(
    conn: psycopg.Connection,
    query: str,
    window: TimeWindow,
    *,
    camera_id: str | None = None,
    province: str | None = None,
    max_distance: float = 2.0,
    limit: int = 100,
) -> list[dict]:
    """ค้นเลขป้ายแบบทนข้อผิดพลาด

    match:
      exact    ตรงกับที่ OCR อ่านทุกตัว
      similar  ต่างกันไม่เกิน max_distance (ตัวที่หน้าตาคล้ายกันนับ 0.4)
      partial  คำค้นเป็นส่วนหนึ่งของป้าย (เช่น รู้แค่ตัวเลข)
    """
    q_clean = clean_plate_text(query)
    q_norm = normalize_for_search(q_clean)
    if not q_norm:
        return []
    where, args = _filters(window, camera_id, province)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT set_config('pg_trgm.similarity_threshold', %s, true)", (str(MIN_TRIGRAM_SIMILARITY),))
        cur.execute(
            f"""SELECT {COLUMNS}, plate_norm FROM sightings
                WHERE plate_norm IS NOT NULL AND {where}
                  AND (plate_norm %% %s OR plate_norm LIKE %s)
                ORDER BY observed_at DESC LIMIT %s""",
            [*args, q_norm, f"%{_escape_like(q_norm)}%", MAX_CANDIDATES],
        )
        candidates = cur.fetchall()

    results = []
    for row in candidates:
        norm = row.pop("plate_norm")
        if row["plate_text"] == q_clean:
            match, dist = "exact", 0.0
        else:
            dist = plate_distance(q_clean, row["plate_text"])
            if dist <= max_distance:
                match = "similar"
            elif q_norm in norm:
                match = "partial"
            else:
                continue
        results.append({**row, "match": match, "distance": dist})
    order = {"exact": 0, "similar": 1, "partial": 2}
    results.sort(key=lambda r: (order[r["match"]], r["distance"], -r["observed_at"].timestamp()))
    return results[:limit]


def browse(
    conn: psycopg.Connection,
    window: TimeWindow,
    *,
    camera_id: str | None = None,
    color: str | None = None,
    vehicle_type: str | None = None,
    limit: int = 100,
) -> list[dict]:
    where, args = _filters(window, camera_id, None)
    attrs: dict[str, Any] = {}
    if color:
        attrs["color"] = {"value": color}
    if vehicle_type:
        attrs["vehicle_type"] = {"value": vehicle_type}
    if attrs:
        where += " AND attributes @> %s"
        args.append(psycopg.types.json.Jsonb(attrs))
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {COLUMNS} FROM sightings WHERE {where} ORDER BY observed_at DESC LIMIT %s", [*args, limit])
        return cur.fetchall()


def journey(conn: psycopg.Connection, journey_id: int) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """SELECT journey_id, subject_type, first_seen, last_seen, plate_text, province, plate_confidence, closed
               FROM journeys WHERE journey_id = %s""",
            (journey_id,),
        )
        j = cur.fetchone()
        if j is None:
            return None
        # journey_id ไม่ได้อยู่ใน partition key: จำกัดช่วงเวลาให้ Postgres ตัด partition ที่ไม่เกี่ยวออก
        cur.execute(
            f"""SELECT {COLUMNS} FROM sightings
                WHERE journey_id = %s AND observed_at >= %s AND observed_at <= %s
                ORDER BY observed_at""",
            (journey_id, j["first_seen"], j["last_seen"]),
        )
        j["sightings"] = cur.fetchall()
    return j


def image_path(conn: psycopg.Connection, sighting_id: UUID, kind: str) -> str | None:
    column = {"crop": "crop_path", "context": "context_path"}[kind]
    row = conn.execute(f"SELECT {column} FROM sightings WHERE sighting_id = %s LIMIT 1", (sighting_id,)).fetchone()
    return row[0] if row else None


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def cameras(conn: psycopg.Connection) -> list[dict]:
    """กล้องที่ยังใช้งานอยู่ (ไม่ใช่ข้อมูลส่วนบุคคล จึงไม่บันทึก audit)"""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT camera_id, name, location FROM cameras WHERE active ORDER BY camera_id")
        return cur.fetchall()
