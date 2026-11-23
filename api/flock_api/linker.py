"""Linker worker: ต่อ sighting ที่ยังไม่มี journey เข้ากับ journey ตามกฎใน linking.py

อ่านจากฐานข้อมูลโดยตรง (ไม่ใช่จากคิว) จึงไม่มีปัญหาแข่งกับ writer และเริ่มใหม่ได้เสมอ
รันได้ทีละตัวเท่านั้น (ใช้ advisory lock กันรันซ้อน)

    flock-linker
"""

from __future__ import annotations

import logging
import os
import signal
import threading
from datetime import timedelta
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from flock_api.config import Settings
from flock_api.linking import Candidate, Decision, Observation, decide
from flock_api.topology import Topology

log = logging.getLogger("flock.linker")

LOCK_KEY = 0x464C4B4C  # "FLKL"

PENDING_SQL = """
SELECT sighting_id, observed_at, camera_id, subject_type, plate_text, plate_confidence, province,
       attributes->'color'->>'value' AS color, attributes->'vehicle_type'->>'value' AS vehicle_type,
       embedding::text AS embedding
FROM sightings
WHERE journey_id IS NULL AND ingested_at < now() - %s
ORDER BY observed_at
LIMIT %s
"""

# journey ที่ยังเปิดอยู่ พร้อม sighting ล่าสุดที่เกิดก่อนหรือพร้อม observation
CANDIDATES_SQL = """
SELECT j.journey_id, j.plate_text, l.camera_id AS last_camera_id, l.observed_at AS last_seen,
       l.attributes->'color'->>'value' AS color, l.attributes->'vehicle_type'->>'value' AS vehicle_type,
       CASE WHEN %(emb)s::vector IS NULL OR l.embedding IS NULL THEN NULL
            ELSE 1 - (l.embedding <=> %(emb)s::vector) END AS similarity
FROM journeys j
CROSS JOIN LATERAL (
    SELECT s.camera_id, s.observed_at, s.attributes, s.embedding
    FROM sightings s
    WHERE s.journey_id = j.journey_id AND s.observed_at <= %(t)s + %(tol)s
    ORDER BY s.observed_at DESC
    LIMIT 1
) l
WHERE NOT j.closed
  AND j.subject_type = %(subject)s
  AND j.last_seen >= %(t)s - %(idle)s
"""


def link_one(conn: psycopg.Connection, row: dict, topo: Topology) -> Decision:
    o = Observation(row["camera_id"], row["observed_at"], row["plate_text"], row["color"], row["vehicle_type"])
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CANDIDATES_SQL, {
            "emb": row["embedding"], "t": row["observed_at"], "tol": timedelta(seconds=2),
            "subject": row["subject_type"], "idle": timedelta(hours=topo.config.journey_idle_hours),
        })
        candidates = [Candidate(**c) for c in cur.fetchall()]
    d = decide(o, candidates, topo)

    if d.journey_id is None:
        journey_id = conn.execute(
            """INSERT INTO journeys (subject_type, first_seen, last_seen, plate_text, province, plate_confidence)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING journey_id""",
            (row["subject_type"], o.observed_at, o.observed_at, row["plate_text"], row["province"],
             row["plate_confidence"]),
        ).fetchone()[0]
    else:
        journey_id = d.journey_id
        conn.execute(
            """UPDATE journeys SET
                   first_seen = least(first_seen, %(t)s),
                   last_seen = greatest(last_seen, %(t)s),
                   -- cast เป็น real ก่อนเทียบ: 0.9 (float8) > 0.9 ที่เก็บเป็น real (0.8999...) จะเป็นจริงเสมอ
                   plate_text = CASE WHEN %(conf)s::real > coalesce(plate_confidence, -1) THEN %(plate)s ELSE plate_text END,
                   province = CASE WHEN %(conf)s::real > coalesce(plate_confidence, -1) THEN %(prov)s ELSE province END,
                   plate_confidence = greatest(plate_confidence, %(conf)s::real)
               WHERE journey_id = %(jid)s""",
            {"t": o.observed_at, "plate": row["plate_text"], "prov": row["province"],
             "conf": row["plate_confidence"] if row["plate_text"] else None, "jid": journey_id},
        )
    conn.execute(
        """UPDATE sightings SET journey_id = %s, link_method = %s, link_score = %s
           WHERE sighting_id = %s AND observed_at = %s""",
        (journey_id, d.method, d.score, row["sighting_id"], row["observed_at"]),
    )
    if topo.is_exit(o.camera_id):
        conn.execute("UPDATE journeys SET closed = true WHERE journey_id = %s", (journey_id,))
    return d


def link_pending(conn: psycopg.Connection, topo: Topology, batch: int = 200) -> dict[str, int]:
    counts: dict[str, int] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(PENDING_SQL, (timedelta(seconds=topo.config.settle_seconds), batch))
        rows = cur.fetchall()
    for row in rows:
        with conn.transaction():
            d = link_one(conn, row, topo)
        counts[d.method] = counts.get(d.method, 0) + 1
    return counts


def close_idle(conn: psycopg.Connection, topo: Topology) -> int:
    return conn.execute(
        "UPDATE journeys SET closed = true WHERE NOT closed AND last_seen < now() - %s",
        (timedelta(hours=topo.config.journey_idle_hours),),
    ).rowcount


def run(settings: Settings, topo: Topology, stop: threading.Event, poll_seconds: float = 1.0) -> dict[str, int]:
    totals: dict[str, int] = {}
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        if not conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)).fetchone()[0]:
            raise SystemExit("มี linker อีกตัวรันอยู่แล้ว")
        log.info("linker started with %d cameras in topology", len(topo.roles))
        while not stop.is_set():
            counts = link_pending(conn, topo)
            for k, v in counts.items():
                totals[k] = totals.get(k, 0) + v
            close_idle(conn, topo)
            if not counts:
                stop.wait(poll_seconds)
    return totals


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    topo = Topology.load(Path(os.environ.get("FLOCK_TOPOLOGY", "/etc/flock/topology.toml")))
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    log.info("linker stopped: %s", run(Settings.from_env(), topo, stop))


if __name__ == "__main__":
    main()
