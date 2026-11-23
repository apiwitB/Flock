"""ข้อตกลงเรื่องคิว (Valkey/Redis Streams) ระหว่างผู้ส่ง event กับ writer

ไม่ผูกกับไลบรารีใด: publish() รับ client อะไรก็ได้ที่มีเมธอด xadd แบบ redis-py
"""

from __future__ import annotations

from typing import Any

from flock_contracts.sighting import SightingEvent

STREAM = "sightings"
DEAD_LETTER_STREAM = "sightings.dead"
WRITER_GROUP = "store"
EVENT_FIELD = "event"

# ความยาวสูงสุดโดยประมาณของ stream: ข้อความที่ ack แล้วถูกตัดทิ้งเมื่อเกินค่านี้
STREAM_MAXLEN = 500_000


def publish(client: Any, event: SightingEvent) -> Any:
    return client.xadd(STREAM, {EVENT_FIELD: event.model_dump_json()}, maxlen=STREAM_MAXLEN, approximate=True)
