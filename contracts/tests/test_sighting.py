import json
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from flock_contracts.sighting import SightingEvent

BKK = timezone(timedelta(hours=7))


def make(**overrides):
    data = {
        "sighting_id": str(uuid.uuid4()),
        "camera_id": "B1-ramp-up",
        "observed_at": "2026-11-23T08:15:00+07:00",
        "subject_type": "vehicle",
        "track_id": "B1-ramp-up.4821",
        "plate": {"text": "1กข 1234", "confidence": 0.93, "province": "กทม", "province_confidence": 0.88},
        "attributes": {"color": {"value": "white", "confidence": 0.81}},
        "embedding": [0.1, 0.2, 0.3],
        "embedding_model": "reid-v0",
        "images": {"crop_path": "2026-11-23/B1-ramp-up/x_crop.jpg", "context_path": "2026-11-23/B1-ramp-up/x_ctx.jpg"},
        "reader_versions": {"plate": "ocr-0.1", "attr": "attr-0.1"},
    }
    data.update(overrides)
    return data


def test_valid_event_is_normalized():
    ev = SightingEvent.model_validate(make())
    assert ev.schema_version == 1
    assert ev.observed_at == datetime(2026, 11, 23, 1, 15, tzinfo=UTC)
    assert ev.observed_at.utcoffset() == timedelta(0)
    assert ev.plate.text == "1กข1234"
    assert ev.plate.province == "กรุงเทพมหานคร"


def test_round_trip_json():
    ev = SightingEvent.model_validate(make())
    again = SightingEvent.model_validate_json(ev.model_dump_json())
    assert again == ev
    assert "กรุงเทพมหานคร" in json.dumps(ev.model_dump(mode="json"), ensure_ascii=False)


def test_plate_and_embedding_are_optional():
    ev = SightingEvent.model_validate(make(plate=None, embedding=None, embedding_model=None))
    assert ev.plate is None and ev.embedding is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"observed_at": "2026-11-23T08:15:00"},  # ไม่มี timezone
        {"subject_type": "person"},  # ยังไม่รองรับในรุ่นแรก
        {"extra_field": 1},
        {"camera_id": "../etc"},
        {"plate": {"text": "กข1234", "confidence": 1.5}},
        {"plate": {"text": " - ", "confidence": 0.5}},
        {"plate": {"text": "กข1234", "confidence": 0.5, "province": "ไม่มีจังหวัดนี้", "province_confidence": 0.5}},
        {"plate": {"text": "กข1234", "confidence": 0.5, "province": "ชลบุรี"}},
        {"embedding": []},
        {"embedding": [0.1, float("nan")]},
        {"embedding_model": None},
        {"schema_version": 2},
    ],
)
def test_invalid_events_rejected(overrides):
    with pytest.raises(ValidationError):
        SightingEvent.model_validate(make(**overrides))


def test_event_is_immutable():
    ev = SightingEvent.model_validate(make())
    with pytest.raises(ValidationError):
        ev.camera_id = "other"


def test_bangkok_time_input_equals_utc_input():
    a = SightingEvent.model_validate(make(observed_at=datetime(2026, 11, 23, 8, 0, tzinfo=BKK)))
    b = SightingEvent.model_validate(make(observed_at="2026-11-23T01:00:00Z"))
    assert a.observed_at == b.observed_at
