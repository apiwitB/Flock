-- session ของผู้ใช้เว็บ เก็บเฉพาะ hash ของ token (ถ้าฐานข้อมูลรั่ว token ก็ยังใช้ไม่ได้)
CREATE TABLE sessions (
    token_hash  bytea PRIMARY KEY,
    user_id     bigint NOT NULL REFERENCES users ON DELETE CASCADE,
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL
);
CREATE INDEX sessions_expires ON sessions (expires_at);
CREATE INDEX sessions_user ON sessions (user_id);

GRANT SELECT, INSERT, DELETE ON sessions TO flock_app;
