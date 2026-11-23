import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
import redis

from flock_api.config import Settings
from flock_contracts import SightingEvent

CAMERAS = ("B1-ramp-up", "L2-north", "G-entry", "G-exit")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    os.environ["FLOCK_IMAGE_ROOT"] = str(tmp_path / "images")
    (tmp_path / "images").mkdir()
    return Settings.from_env()


@pytest.fixture(autouse=True)
def clean_state(settings):
    """ล้างฐานข้อมูลและคิวก่อนทุกเทสต์ (ใช้ role เจ้าของ เพราะแอปลบ audit_log ไม่ได้)"""
    with psycopg.connect(os.environ["FLOCK_OWNER_DATABASE_URL"], autocommit=True) as conn:
        conn.execute("TRUNCATE sightings, journeys, sessions, audit_log, users, cameras RESTART IDENTITY CASCADE")
        for cam in CAMERAS:
            conn.execute("INSERT INTO cameras (camera_id, name) VALUES (%s, %s)", (cam, cam))
    redis.Redis.from_url(settings.queue_url).flushdb()
    yield


@pytest.fixture
def conn(settings):
    with psycopg.connect(settings.database_url, autocommit=True) as c:
        yield c


@pytest.fixture
def owner_conn():
    with psycopg.connect(os.environ["FLOCK_OWNER_DATABASE_URL"], autocommit=True) as c:
        yield c


@pytest.fixture
def r(settings):
    return redis.Redis.from_url(settings.queue_url)


def make_event(
    plate: str | None = "1กข1234",
    *,
    camera: str = "B1-ramp-up",
    ago: timedelta = timedelta(minutes=10),
    color: str = "white",
    embedding: list[float] | None = None,
    crop_path: str | None = None,
    plate_confidence: float = 0.9,
    **overrides,
) -> SightingEvent:
    sid = uuid.uuid4()
    data = {
        "sighting_id": sid,
        "camera_id": camera,
        "observed_at": datetime.now(UTC) - ago,
        "subject_type": "vehicle",
        "track_id": f"{camera}.1",
        "plate": {"text": plate, "confidence": plate_confidence, "province": "กรุงเทพมหานคร", "province_confidence": 0.8}
        if plate
        else None,
        "attributes": {"color": {"value": color, "confidence": 0.8}, "vehicle_type": {"value": "sedan", "confidence": 0.7}},
        "embedding": embedding,
        "embedding_model": "reid-test" if embedding else None,
        "images": {"crop_path": crop_path or f"x/{sid}_crop.jpg", "context_path": f"x/{sid}_context.jpg"},
        "reader_versions": {"plate": "test"},
    }
    data.update(overrides)
    return SightingEvent.model_validate(data)
