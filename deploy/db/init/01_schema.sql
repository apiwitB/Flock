-- schema รุ่นแรก (schema_version 1 ของ Sighting event)
-- ภายหลังย้ายไปจัดการด้วย Alembic ใน api/ ไฟล์นี้ใช้ตั้งฐานข้อมูลใหม่สำหรับพัฒนา

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO flock_app;

-- กล้อง ------------------------------------------------------------------------
CREATE TABLE cameras (
    camera_id   text PRIMARY KEY CHECK (camera_id ~ '^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$'),
    name        text NOT NULL,
    location    text,
    active      boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- เส้นทางของรถหนึ่งคันในหนึ่งครั้งที่เข้าอาคาร (Linker สร้าง) -----------------------------
CREATE TABLE journeys (
    journey_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    subject_type  text NOT NULL,
    first_seen    timestamptz NOT NULL,
    last_seen     timestamptz NOT NULL,
    plate_text    text,
    province      text,
    closed        boolean NOT NULL DEFAULT false,
    CHECK (last_seen >= first_seen)
);
CREATE INDEX journeys_last_seen ON journeys (last_seen);
CREATE INDEX journeys_plate_trgm ON journeys USING gin (plate_text gin_trgm_ops);

-- Sighting: 1 แถวต่อ 1 event แบ่ง partition รายวัน (UTC) ลบตามรอบด้วยการ drop partition --------
CREATE TABLE sightings (
    sighting_id          uuid NOT NULL,
    observed_at          timestamptz NOT NULL,
    camera_id            text NOT NULL REFERENCES cameras,
    subject_type         text NOT NULL,
    local_track_id       text NOT NULL,          -- track_id ใน event (ภายในกล้องเดียว)
    plate_text           text,                   -- ตามที่ OCR อ่าน (ผ่าน clean_plate_text)
    plate_norm           text,                   -- normalize_for_search(plate_text) ใช้กับ pg_trgm
    plate_confidence     real CHECK (plate_confidence BETWEEN 0 AND 1),
    province             text,
    province_confidence  real CHECK (province_confidence BETWEEN 0 AND 1),
    attributes           jsonb NOT NULL DEFAULT '{}',
    -- มิติต้องตรงกับ embedding model ถ้าเปลี่ยนโมเดลต้องทำ migration
    embedding            vector(512),
    embedding_model      text,
    crop_path            text NOT NULL,
    context_path         text NOT NULL,
    reader_versions      jsonb NOT NULL,
    schema_version       smallint NOT NULL,
    ingested_at          timestamptz NOT NULL DEFAULT now(),
    -- Linker เติมภายหลัง
    journey_id           bigint REFERENCES journeys ON DELETE SET NULL,
    link_method          text CHECK (link_method IN ('exact', 'similar_plate', 'guess')),
    link_score           real,
    PRIMARY KEY (sighting_id, observed_at),
    CHECK ((plate_text IS NULL) = (plate_norm IS NULL)),
    CHECK ((embedding IS NULL) = (embedding_model IS NULL)),
    CHECK ((journey_id IS NULL) = (link_method IS NULL))
) PARTITION BY RANGE (observed_at);

CREATE INDEX sightings_time ON sightings (observed_at);
CREATE INDEX sightings_camera_time ON sightings (camera_id, observed_at);
CREATE INDEX sightings_journey ON sightings (journey_id) WHERE journey_id IS NOT NULL;
CREATE INDEX sightings_plate_trgm ON sightings USING gin (plate_norm gin_trgm_ops);
CREATE INDEX sightings_attributes ON sightings USING gin (attributes jsonb_path_ops);
CREATE INDEX sightings_embedding ON sightings USING hnsw (embedding vector_cosine_ops);

-- ผู้ใช้และ audit log -------------------------------------------------------------
CREATE TABLE users (
    user_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username       text NOT NULL UNIQUE,
    password_hash  text NOT NULL,                -- argon2
    role           text NOT NULL CHECK (role IN ('viewer', 'investigator', 'admin')),
    active         boolean NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now()
);

-- ไม่อยู่ในรอบลบ 30 วัน (ระยะเก็บรอเจ้าของระบบกำหนด)
CREATE TABLE audit_log (
    audit_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at            timestamptz NOT NULL DEFAULT now(),
    user_id       bigint REFERENCES users,
    action        text NOT NULL,                 -- เช่น search.plate, search.image, view.journey
    query         jsonb NOT NULL DEFAULT '{}',
    result_count  integer,
    client_ip     inet
);
CREATE INDEX audit_log_at ON audit_log (at);
CREATE INDEX audit_log_user_at ON audit_log (user_id, at);

-- partition รายวัน --------------------------------------------------------------
-- สร้าง partition ตั้งแต่ (วันนี้ - days_back) ถึง (วันนี้ + days_ahead) ตามเวลา UTC
CREATE FUNCTION flock_ensure_partitions(days_back int DEFAULT 1, days_ahead int DEFAULT 7)
RETURNS int LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    d date;
    created int := 0;
    name text;
BEGIN
    FOR d IN SELECT generate_series((now() AT TIME ZONE 'UTC')::date - days_back,
                                    (now() AT TIME ZONE 'UTC')::date + days_ahead, interval '1 day')::date
    LOOP
        name := format('sightings_p%s', to_char(d, 'YYYYMMDD'));
        IF to_regclass(name) IS NULL THEN
            EXECUTE format('CREATE TABLE %I PARTITION OF sightings FOR VALUES FROM (%L) TO (%L)',
                           name, (d::timestamp AT TIME ZONE 'UTC'), ((d + 1)::timestamp AT TIME ZONE 'UTC'));
            created := created + 1;
        END IF;
    END LOOP;
    RETURN created;
END $$;

-- ลบข้อมูลเก่ากว่า keep_days วัน: drop partition ของ sightings แล้วลบ journeys ที่จบก่อนรอบ
-- ภาพในที่เก็บไฟล์ต้องลบด้วยงานแยก (โฟลเดอร์ตามวันเดียวกัน)
CREATE FUNCTION flock_apply_retention(keep_days int DEFAULT 30)
RETURNS TABLE (dropped_partition text) LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    cutoff date := (now() AT TIME ZONE 'UTC')::date - keep_days;
    part record;
BEGIN
    IF keep_days < 1 THEN
        RAISE EXCEPTION 'keep_days must be >= 1';
    END IF;
    FOR part IN
        SELECT c.relname
        FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
        WHERE i.inhparent = 'sightings'::regclass
          AND c.relname ~ '^sightings_p[0-9]{8}$'
          AND to_date(substr(c.relname, 12), 'YYYYMMDD') < cutoff
        ORDER BY c.relname
    LOOP
        EXECUTE format('DROP TABLE %I', part.relname);
        dropped_partition := part.relname;
        RETURN NEXT;
    END LOOP;
    DELETE FROM journeys WHERE last_seen < (cutoff::timestamp AT TIME ZONE 'UTC');
END $$;

REVOKE ALL ON FUNCTION flock_apply_retention(int) FROM PUBLIC;
REVOKE ALL ON FUNCTION flock_ensure_partitions(int, int) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION flock_ensure_partitions(int, int) TO flock_app;

SELECT flock_ensure_partitions();

-- สิทธิ์ของแอป ---------------------------------------------------------------------
GRANT SELECT ON cameras TO flock_app;
GRANT SELECT, INSERT, UPDATE ON sightings, journeys TO flock_app;
GRANT SELECT, INSERT, UPDATE ON users TO flock_app;
GRANT SELECT, INSERT ON audit_log TO flock_app;     -- ไม่มี UPDATE/DELETE/TRUNCATE: แก้ย้อนหลังไม่ได้
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO flock_app;
-- partition ใหม่ที่ฟังก์ชันสร้างได้สิทธิ์ผ่านตารางแม่ (แอปเข้าถึงผ่าน sightings เท่านั้น)
