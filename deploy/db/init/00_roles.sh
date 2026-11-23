#!/bin/sh
# role ของแอป: ไม่ใช่เจ้าของตาราง จึงถูกจำกัดสิทธิ์ได้ (เช่น ห้ามแก้ audit_log)
set -eu
psql -v ON_ERROR_STOP=1 -v app_password="$FLOCK_APP_PASSWORD" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE flock_app LOGIN PASSWORD :'app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
SQL
