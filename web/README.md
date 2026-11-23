# web: หน้าเว็บค้นหารถ

React 18 + Vite + TypeScript, TanStack Query, React Router ไม่ใช้ฟอนต์หรือ CDN ภายนอก (ใช้ในเครือข่ายปิดได้)

## หน้า

| path | สิทธิ์ขั้นต่ำ | ทำอะไร |
|---|---|---|
| `/login` | - | เข้าสู่ระบบ |
| `/plates` | investigator | ค้นเลขป้าย (ทนผิด) |
| `/browse` | viewer | ดูรายการรถตามกล้อง/เวลา/สี/ประเภท |
| `/journey/:id` | investigator | ไทม์ไลน์เส้นทางของรถหนึ่งคัน |

route ของเว็บห้ามขึ้นต้นด้วย `/auth` `/search` `/sightings` `/journeys` `/cameras` เพราะ path เหล่านี้ส่งต่อไปยัง API

- เวลาที่กรอกถือเป็นเวลาไทย (UTC+7) และส่งเป็น ISO พร้อม `+07:00`
- หน้ารายการไม่โหลดภาพเอง ต้องกด "ดูภาพ" เพราะการเปิดภาพทุกครั้งถูกบันทึกใน audit log หน้าเส้นทางโหลดภาพรถของทุกจุดให้เลย ส่วนภาพมุมกว้างต้องกดเปิดเอง
- ป้ายความมั่นใจ (ชัด / ป้ายคล้าย / เดา / ตรงบางส่วน / จุดเริ่ม) กำหนดไว้ที่เดียวคือ `src/lib/confidence.ts`

## พัฒนา

ต้องมี Search API รันอยู่ที่ `http://127.0.0.1:8000` (Vite ส่งต่อ path ของ API ไปให้)

```powershell
cd D:\Flock\web
npm ci
npm run dev        # http://127.0.0.1:5173
```

ถ้า API อยู่ที่อื่น: `$env:FLOCK_API_TARGET = "http://127.0.0.1:8001"; npm run dev`

## build และเทสต์

```powershell
npm run build      # tsc --noEmit แล้ว vite build ได้ไฟล์ใน dist/
npm test           # vitest
```

production: Caddy เสิร์ฟ `dist/` (ทุก path ที่ไม่ใช่ไฟล์ให้ตอบ `index.html`) และส่งต่อ path ของ API ไปยัง uvicorn

ถ้า Windows Application Control บล็อก esbuild/rollup ให้รันใน Docker แทน (ลบ `node_modules` ก่อน):

```bash
MSYS_NO_PATHCONV=1 docker run --rm -v D:/Flock/web:/web -w /web node:22-slim sh -c "npm ci && npm run build && npm test"
```
