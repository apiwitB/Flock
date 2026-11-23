-- รันเป็น flock_owner: psql -v ON_ERROR_STOP=1 -f /tests/test_schema.sql
-- ทุกอย่างอยู่ใน transaction และ rollback ตอนจบ ฐานข้อมูลจึงไม่เปลี่ยน
\set QUIET on
BEGIN;

INSERT INTO cameras (camera_id, name) VALUES ('B1-ramp-up', 'ทางขึ้น B1'), ('L2-north', 'ชั้น 2 ฝั่งเหนือ');

-- 1) partition: ต้องมีของวันนี้ และสร้างวันย้อนหลังเพิ่มได้
DO $$ BEGIN
    ASSERT to_regclass(format('sightings_p%s', to_char(now() AT TIME ZONE 'UTC', 'YYYYMMDD'))) IS NOT NULL,
        'missing today partition';
    ASSERT flock_ensure_partitions(40, 0) = 39, 'expected 39 new back-dated partitions';
    ASSERT flock_ensure_partitions(40, 0) = 0, 'ensure_partitions must be idempotent';
END $$;

-- 2) เขียนข้อมูลในฐานะแอป
SET LOCAL ROLE flock_app;

INSERT INTO sightings (sighting_id, observed_at, camera_id, subject_type, local_track_id,
                       plate_text, plate_norm, plate_confidence, attributes, crop_path, context_path,
                       reader_versions, schema_version, embedding, embedding_model)
VALUES
  (gen_random_uuid(), now() - interval '1 hour', 'B1-ramp-up', 'vehicle', 't1', '1กข1234', '1กข1204', 0.95,
   '{"color": {"value": "white", "confidence": 0.8}}', 'a', 'b', '{"plate":"0.1"}', 1,
   array_fill(0.1, ARRAY[512])::vector, 'reid-v0'),
  (gen_random_uuid(), now() - interval '50 minutes', 'L2-north', 'vehicle', 't9', '1กช1234', '1กข1204', 0.71,
   '{"color": {"value": "white", "confidence": 0.7}}', 'a', 'b', '{"plate":"0.1"}', 1, NULL, NULL),
  (gen_random_uuid(), now() - interval '35 days', 'B1-ramp-up', 'vehicle', 't0', 'ฮฮ9', 'ฮฮ9', 0.9,
   '{}', 'a', 'b', '{"plate":"0.1"}', 1, NULL, NULL);

-- 3) ค้นป้ายแบบทนผิดด้วย pg_trgm บน plate_norm และค้นสีด้วย jsonb
DO $$ BEGIN
    ASSERT (SELECT count(*) FROM sightings WHERE plate_norm % '1กข1204') = 2, 'trigram search';
    ASSERT (SELECT count(*) FROM sightings WHERE attributes @> '{"color": {"value": "white"}}') = 2, 'jsonb search';
    ASSERT (SELECT plate_text FROM sightings WHERE embedding IS NOT NULL
            ORDER BY embedding <=> array_fill(0.1, ARRAY[512])::vector LIMIT 1) = '1กข1234', 'vector search';
END $$;

-- 4) audit log: แอปเพิ่มได้ แต่แก้/ลบไม่ได้
INSERT INTO audit_log (action, query, result_count) VALUES ('search.plate', '{"plate":"1กข1234"}', 2);
DO $$ BEGIN
    BEGIN
        UPDATE audit_log SET action = 'x';
        RAISE EXCEPTION 'UPDATE on audit_log should be denied';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
    BEGIN
        DELETE FROM audit_log;
        RAISE EXCEPTION 'DELETE on audit_log should be denied';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
    BEGIN
        PERFORM flock_apply_retention(30);
        RAISE EXCEPTION 'app must not run retention';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
END $$;

-- 5) retention: ข้อมูล 35 วันก่อนหายไป ข้อมูลวันนี้ยังอยู่
RESET ROLE;
DO $$ BEGIN
    ASSERT (SELECT count(*) FROM flock_apply_retention(30)) >= 9, 'should drop partitions older than 30 days';
    ASSERT (SELECT count(*) FROM sightings) = 2, 'old sighting must be gone, recent ones kept';
    ASSERT to_regclass(format('sightings_p%s', to_char(now() AT TIME ZONE 'UTC', 'YYYYMMDD'))) IS NOT NULL;
END $$;

-- 6) constraint: ป้ายต้องมี plate_norm คู่กัน
DO $$ BEGIN
    BEGIN
        INSERT INTO sightings (sighting_id, observed_at, camera_id, subject_type, local_track_id, plate_text,
                               crop_path, context_path, reader_versions, schema_version)
        VALUES (gen_random_uuid(), now(), 'B1-ramp-up', 'vehicle', 't', 'กข1', 'a', 'b', '{}', 1);
        RAISE EXCEPTION 'plate_text without plate_norm should fail';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
END $$;

\echo 'schema tests: OK'
ROLLBACK;
