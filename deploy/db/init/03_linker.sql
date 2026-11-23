-- Linker: ต่อ sighting เข้ากับ journey
-- 'new' = sighting แรกของ journey ที่เปิดใหม่ (ไม่พบคันที่ตรงกัน)
ALTER TABLE sightings DROP CONSTRAINT sightings_link_method_check;
ALTER TABLE sightings ADD CONSTRAINT sightings_link_method_check
    CHECK (link_method IN ('new', 'exact', 'similar_plate', 'guess'));

-- ป้ายที่ดีที่สุดของ journey มาจาก sighting ที่ OCR มั่นใจที่สุด
ALTER TABLE journeys ADD COLUMN plate_confidence real CHECK (plate_confidence BETWEEN 0 AND 1);

CREATE INDEX sightings_unlinked ON sightings (observed_at) WHERE journey_id IS NULL;
CREATE INDEX journeys_open ON journeys (last_seen) WHERE NOT closed;
