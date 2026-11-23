# หน้าเว็บ (React) + Caddy
# build จาก root ของ repo: docker build -f deploy/web/Dockerfile .
# (docker compose ใน deploy/ ตั้ง context: .. ไว้แล้ว)

# --- build: web/ -> web/dist ---------------------------------------------------
FROM node:22-slim AS build
WORKDIR /src/web
# คัดลอก lockfile ก่อน เพื่อให้ cache ชั้น npm ci ไว้ได้ถ้า dependency ไม่เปลี่ยน
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# --- run: Caddy เสิร์ฟไฟล์ static และ reverse proxy ไป api ----------------------
FROM caddy:2
COPY deploy/web/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/web/dist /srv
EXPOSE 80
