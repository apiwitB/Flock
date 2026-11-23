# api: writer + Search API

## ส่วนประกอบ

| ส่วน | ทำอะไร | รัน |
|---|---|---|
| `flock_api.writer` | อ่าน Sighting event จากคิว (Valkey Streams) แล้วเขียนลง Postgres | `flock-writer` (service `writer`) |
| `flock_api.app` | Search API + login + audit log | `uvicorn flock_api.app:app` (service `api`) |
| `flock_api.linker` | ต่อ sighting ข้ามกล้องเป็น journey (เส้นทางของรถหนึ่งคัน) | `flock-linker` (service `linker`) |
| `flock_api.users` | สร้าง/ปิดบัญชีผู้ใช้ | `flock-users` |

## writer

- event เดิมที่ถูกส่งซ้ำจะไม่สร้างแถวซ้ำ (`ON CONFLICT DO NOTHING` บน `sighting_id`)
- เริ่มทำงานแล้วจะเก็บข้อความค้างก่อน ทั้งของตัวเองและของ writer ตัวอื่นที่ค้างเกิน 60 วินาที จากนั้นจึงอ่านข้อความใหม่
- event ที่เขียนไม่ได้เพราะตัวข้อมูลเองจะย้ายไปที่ `sightings.dead` พร้อมเหตุผล แล้ว ack ทิ้ง

  | reason | ความหมาย |
  |---|---|
  | `invalid` | ไม่ผ่าน schema |
  | `unknown_camera` | กล้องยังไม่ได้ลงทะเบียนในตาราง `cameras` |
  | `too_old` | เก่ากว่า 30 วัน |
  | `clock_skew` | เวลาเลยปัจจุบันไปเกิน 7 วัน |
  | `bad_data` | เช่น มิติของ embedding ไม่ใช่ 512 |

- event ที่มาช้า (เช่น 5 วันก่อน) writer สร้าง partition ของวันนั้นให้เอง
- ถ้าฐานข้อมูลล่ม writer จะไม่ ack ข้อความยังค้างอยู่ในคิว และถูกประมวลผลใหม่เมื่อ writer กลับมา

## linker

อ่าน sighting ที่ยังไม่มี journey จากฐานข้อมูลตามลำดับเวลา แล้วตัดสินตามกฎใน `linking.py`:

| link_method | เงื่อนไข | score |
|---|---|---|
| `exact` | ป้ายตรงทุกตัว และเดินทางมาทันตามผังอาคาร | 1.0 |
| `similar_plate` | ป้ายต่างกันไม่เกิน `similar_max_distance`, สี/ประเภทไม่ขัด, เดินทางทัน | 1 - ระยะ/(max+1) |
| `guess` | ไม่มีป้ายให้เทียบ: embedding คล้ายเกินเกณฑ์ ชนะคันรองชัดเจน จากกล้องติดกันในช่วงเวลาที่วิ่งปกติ | cosine similarity |
| `new` | ไม่เข้าเงื่อนไขใดเลย หรือกำกวม → เปิด journey ใหม่ | - |

- ถ้าไม่แน่ใจจะเปิด journey ใหม่เสมอ เช่น ป้ายคล้ายกับสอง journey เท่ากัน, embedding ใกล้กันสองคัน, หรือป้ายตรงกันแต่เดินทางไม่ทัน
- ไม่ "เดา" ข้ามป้ายที่ขัดกัน: ถ้าทั้งสองฝั่งมีป้ายแต่ป้ายต่างกัน ไม่ต่อด้วย embedding
- ผังอาคารและค่าเกณฑ์อยู่ใน `deploy/topology.example.toml` (คัดลอกเป็น `topology.toml` สำหรับอาคารจริง)
- journey ถูกปิดเมื่อเห็นรถที่กล้อง `exit` หรือไม่มีใครเห็นนานเกิน `journey_idle_hours`
- ป้ายของ journey ใช้ค่าที่ OCR มั่นใจที่สุดในเส้นทาง
- รันได้ทีละตัวเท่านั้น (advisory lock)

ข้อจำกัดที่รู้อยู่:
- event ที่มาช้ากว่า `settle_seconds` และเกิดก่อน sighting ที่ต่อไปแล้ว อาจกลายเป็น journey ใหม่ โดยเฉพาะถ้ามาหลังจาก journey ถูกปิดที่ทางออกแล้ว
- ยังไม่มีการรวม journey สองอันที่ทีหลังพบว่าเป็นคันเดียวกัน
- เกณฑ์ `guess_min_similarity` / `guess_margin` เป็นค่าตั้งต้น ต้องปรับเมื่อมี embedding model จริง

## Search API

| endpoint | สิทธิ์ขั้นต่ำ | ทำอะไร |
|---|---|---|
| `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` | - | session cookie (HttpOnly, SameSite=Strict) |
| `GET /cameras` | viewer | รายชื่อกล้องที่ใช้งานอยู่ `[{camera_id, name, location}]` เรียงตาม `camera_id` (ไม่ใช่ข้อมูลส่วนบุคคล จึงไม่บันทึก audit) |
| `GET /sightings?from&to&camera_id&color&vehicle_type` | viewer | รายการรถตามกล้อง/เวลา/ลักษณะ |
| `GET /search/plates?q&from&to&camera_id&province&max_distance` | investigator | ค้นเลขป้าย ทนผิด ผลมีป้ายบอก `exact` / `similar` / `partial` |
| `GET /journeys/{id}` | investigator | ไทม์ไลน์ของรถหนึ่งคัน พร้อมวิธีต่อแต่ละจุด และ `weakest_link` (ช่วงที่มั่นใจน้อยที่สุดในเส้นทาง) |
| `GET /sightings/{id}/image/{crop\|context}` | investigator | เปิดภาพ |

- ช่วงเวลาค่าเริ่มคือ 24 ชม.ล่าสุด กว้างได้ไม่เกิน 31 วัน ต้องระบุ timezone เสมอ เช่น `2026-11-23T08:00:00+07:00`
- **ทุกคำค้นและการเปิดภาพถูกบันทึกใน `audit_log`** รวมถึงการ login ไม่สำเร็จ และการเปิดภาพที่ตอบ 404
- เอกสาร API อัตโนมัติอยู่ที่ http://127.0.0.1:8080/docs (ผ่าน Caddy) หรือ http://127.0.0.1:8000/docs (ตรง)

### IP ของผู้ใช้ใน audit_log (หลัง Caddy)

- api รัน uvicorn ด้วย `--proxy-headers --forwarded-allow-ips 172.31.250.10` คือเชื่อ `X-Forwarded-For` **เฉพาะ** request ที่มาจาก Caddy
  (service `web` มี IP คงที่ในเครือข่าย `edge` 172.31.250.0/24 ดู `deploy/docker-compose.yml`) ถ้าเปลี่ยน IP ต้องแก้ทั้งสองที่
- Caddy ไม่เชื่อ `X-Forwarded-For` ที่ผู้ใช้ส่งมา แต่ตั้งค่าใหม่เป็น IP ที่ต่อเข้ามาจริง ผู้ใช้จึงปลอม IP ใน audit ไม่ได้
- request ที่ยิงตรงเข้า api (127.0.0.1:8000 หรือจาก container อื่น) บันทึก IP ของผู้ต่อจริง ไม่สน `X-Forwarded-For`
- โค้ดอ่าน `request.client.host` เท่านั้น (`_client_ip` ใน `app.py`) ซึ่ง uvicorn เขียนทับให้แล้ว
- บน Docker Desktop (Windows) การ publish port ผ่าน proxy ของ Docker ทำให้ IP ที่ Caddy เห็นจากเบราว์เซอร์บนเครื่องเดียวกันเป็น
  gateway ของเครือข่าย (เช่น 172.31.250.1) ไม่ใช่ IP เครื่องผู้ใช้ เครื่องจริงบน Linux ต้องตรวจอีกครั้งว่าได้ IP ของเครื่องลูกข่ายจริง

## เปิดหน้าเว็บ

```powershell
cd D:\Flock\deploy; docker compose up -d --build
```

แล้วเปิด http://127.0.0.1:8080 (Caddy เสิร์ฟ React app จาก `web/` และส่งต่อ `/auth`, `/search`, `/sightings`, `/journeys`, `/cameras` ไป api)
ตอนพัฒนาเป็น HTTP ล้วน วิธีเปลี่ยนเป็น HTTPS บนเครื่องจริงอยู่ใน `deploy/web/Caddyfile` (เปิด HTTPS แล้วต้องลบ `FLOCK_COOKIE_SECURE: "false"`)

## สร้างผู้ใช้คนแรก

```powershell
docker compose -f D:\Flock\deploy\docker-compose.yml exec api flock-users create admin --role admin
```

## เทสต์ (ใช้ฐานข้อมูลและคิวแยก ไม่แตะข้อมูลสำหรับพัฒนา)

```powershell
cd D:\Flock\deploy; docker compose -p flock-test -f docker-compose.yml -f docker-compose.test.yml run --rm --build tests; docker compose -p flock-test -f docker-compose.yml -f docker-compose.test.yml down -v
```

## ยังไม่ได้ทำ

- จำกัดจำนวนครั้งที่ login ผิด (rate limit / lockout)
- endpoint จัดการผู้ใช้และกล้องสำหรับ admin (ตอนนี้ใช้ CLI และ SQL)
- ค้นด้วยภาพ (ต้องมี embedding model ก่อน)
- ลบไฟล์ภาพตามรอบ 30 วัน และกำหนดระยะเก็บของ `sightings.dead` (ใน dead-letter มีเลขป้ายอยู่ด้วย)
- HTTPS บนเครื่องจริง (ตอนนี้ Caddy ฟัง HTTP :80 สำหรับพัฒนา)
