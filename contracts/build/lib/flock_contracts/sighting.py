"""Sighting event: ข้อกำหนดเดียวที่ส่วนอ่านภาพและส่วนเก็บ/ค้นหาใช้คุยกัน (README ข้อ 5)

กฎการเปลี่ยนเวอร์ชัน:
- เพิ่มฟิลด์ที่ไม่บังคับ → ไม่ต้องขึ้นเวอร์ชัน
- ลบ/เปลี่ยนความหมาย/บังคับฟิลด์ใหม่ → ขึ้น SCHEMA_VERSION และ writer ต้องรับได้ทั้งสองเวอร์ชันช่วงเปลี่ยนผ่าน
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from flock_contracts.plates import clean_plate_text
from flock_contracts.provinces import normalize_province

SCHEMA_VERSION = 1

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SubjectType(StrEnum):
    VEHICLE = "vehicle"


class Plate(_Strict):
    text: Annotated[str, Field(min_length=1, max_length=16)]
    confidence: Confidence
    province: str | None = None
    province_confidence: Confidence | None = None

    @field_validator("text")
    @classmethod
    def _clean_text(cls, v: str) -> str:
        cleaned = clean_plate_text(v)
        if not cleaned:
            raise ValueError("plate text is empty after cleaning")
        return cleaned

    @field_validator("province")
    @classmethod
    def _known_province(cls, v: str | None) -> str | None:
        if v is None:
            return None
        norm = normalize_province(v)
        if norm is None:
            raise ValueError(f"unknown province: {v!r}")
        return norm

    @model_validator(mode="after")
    def _province_pair(self) -> Plate:
        if (self.province is None) != (self.province_confidence is None):
            raise ValueError("province and province_confidence must be set together")
        return self


class Attribute(_Strict):
    value: Annotated[str, Field(min_length=1, max_length=64)]
    confidence: Confidence


class Images(_Strict):
    crop_path: Annotated[str, Field(min_length=1)]
    context_path: Annotated[str, Field(min_length=1)]


class SightingEvent(_Strict):
    schema_version: Literal[1] = SCHEMA_VERSION
    sighting_id: UUID
    camera_id: Identifier
    observed_at: AwareDatetime
    subject_type: SubjectType
    track_id: Identifier
    plate: Plate | None = None
    attributes: dict[Identifier, Attribute] = Field(default_factory=dict)
    embedding: list[float] | None = None
    embedding_model: str | None = None
    images: Images
    reader_versions: dict[Identifier, Annotated[str, Field(min_length=1)]]

    @field_validator("observed_at")
    @classmethod
    def _to_utc(cls, v: datetime) -> datetime:
        return v.astimezone(UTC)

    @field_validator("embedding")
    @classmethod
    def _finite_embedding(cls, v: list[float] | None) -> list[float] | None:
        if v is None:
            return None
        if not v:
            raise ValueError("embedding must not be empty; use null instead")
        if not all(math.isfinite(x) for x in v):
            raise ValueError("embedding contains NaN or infinity")
        return v

    @model_validator(mode="after")
    def _embedding_needs_model(self) -> SightingEvent:
        if (self.embedding is None) != (self.embedding_model is None):
            raise ValueError("embedding and embedding_model must be set together")
        return self
