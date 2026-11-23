# Stack ที่เสนอ — ระบบติดตามรถในอาคารจอดรถ

วันที่: 2026-11-23 · สถานะ: ร่าง รอเจ้าของระบบอนุมัติ · อ้างอิง: [README.md](README.md) (แนวทาง C)

หลักการเลือก:
- ใบอนุญาตต้องใช้เชิงพาณิชย์ได้ (หลีกเลี่ยง AGPL และชุดข้อมูลที่จำกัดเฉพาะงานวิจัย)
- ส่วนอ่านภาพกับส่วนเก็บและค้นหาคุยกันผ่าน Sighting event เท่านั้น
- ตึกเดียว GPU เดียว เลือกของที่เรียบง่ายก่อน และวาง interface ไว้ให้เปลี่ยนภายหลัง

## 1. ภาพรวม

```
กล้อง RTSP
  └─► [vision-worker]  Python + PyAV/GStreamer (NVDEC) + TensorRT
        ├─ Detector (RT-DETR / YOLOX)  → ByteTrack
        ├─ PlateReader (PaddleOCR / PARSeq ฝึกกับป้ายไทย + classifier จังหวัด)
        └─ AttributeReader (สี/ประเภท + ReID embedding)
              │  Sighting event (Pydantic, มี schema_version)
              ▼
        Valkey Streams (consumer groups)
              │
  ┌───────────┴────────────┐
[linker-worker]      [ingest-writer]
  └──────────┬─────────────┘
             ▼
   Postgres 17 + pgvector + pg_trgm   +   ที่เก็บภาพ (filesystem แยกโฟลเดอร์ตามวัน)
             ▼
   FastAPI (search + auth + audit)  ◄─  Caddy (TLS)  ◄─  React SPA
```

## 2. ส่วนอ่านภาพ (GPU)

| ส่วน | ตัวเลือก | ใบอนุญาต | เหตุผล / ข้อควรระวัง |
|---|---|---|---|
| Decode | PyAV หรือ GStreamer + NVDEC | LGPL / LGPL | ถอดรหัสบน GPU ไม่กิน CPU ถ้ากล้องเยอะค่อยพิจารณา DeepStream |
| Inference | TensorRT (export ผ่าน ONNX) | NVIDIA SLA | เร็วที่สุดบน NVIDIA ช่วงทดลองใช้ ONNX Runtime ได้ |
| Detector | **RT-DETR** หรือ **YOLOX** | Apache-2.0 | ไม่ใช้ Ultralytics YOLOv8/11 เพราะเป็น AGPL-3.0 ถ้าจะใช้ต้องซื้อ license |
| Tracker | ByteTrack | MIT | ติดตามรถภายในกล้องเดียว |
| OCR ป้าย | PaddleOCR หรือ PARSeq, fine-tune ด้วยภาพจริงของอาคาร | Apache-2.0 | ป้ายสองบรรทัด: บรรทัดทะเบียนใช้ OCR ส่วนจังหวัดใช้ classifier 77 คลาส |
| สี / ประเภทรถ | classifier เล็ก (EfficientNet / ResNet) | Apache-2.0 / BSD | ยี่ห้อ/รุ่นยังไม่ทำในรุ่นแรก (README ข้อ 10) |
| Embedding | ReID model (เช่น FastReID) | Apache-2.0 | **ห้ามใช้ weights ที่ฝึกจาก VeRi-776 / VehicleID** ในงานจริง เพราะชุดข้อมูลจำกัดเฉพาะงานวิจัย ต้องฝึกจากภาพของอาคารเอง |
| Label ข้อมูล | CVAT หรือ Label Studio | MIT / Apache-2.0 | เตรียมข้อมูลฝึก OCR และ ReID ในขั้นที่ 1 |

Reader ทุกตัวต้องทำตาม interface เดียวกัน (รับภาพรถที่ตัดแล้ว คืนค่า attributes + confidence + reader_version) เพื่อเพิ่ม Reader ใหม่ เช่น `person` ได้โดยไม่ต้องแก้ส่วนอื่น

## 3. คิวและข้อกำหนด event

- **Valkey Streams** (fork ของ Redis ใบอนุญาต BSD เพราะ Redis 7.4+ ไม่ใช่ BSD แล้ว) ใช้ consumer group และ ack ทำให้ไม่เสีย event ตอน worker ล้ม ตั้ง `MAXLEN` กันคิวโตไม่หยุด
- Sighting event เขียนเป็น **Pydantic model** ในแพ็กเกจกลาง `contracts/` แล้ว export เป็น JSON Schema
- ทุก event มี `schema_version` ถ้าเปลี่ยนแบบไม่เข้ากันกับของเดิมต้องขึ้นเวอร์ชันหลัก และ writer ต้องรับได้ทั้งสองเวอร์ชันในช่วงเปลี่ยนผ่าน

## 4. ส่วนเก็บข้อมูล

**Postgres 17**
- `pgvector` (index แบบ HNSW) สำหรับค้นด้วยภาพและให้ Linker ใช้เทียบ embedding
- `pg_trgm` + `fuzzystrmatch` สำหรับค้นป้ายแบบทน OCR ผิด
  - เก็บทั้ง `plate_raw` และ `plate_normalized` (ผ่านตารางตัวที่ OCR สับสนบ่อย เช่น ข/ช, ฎ/ฏ, ด/ต, 8/B, 0/O)
- **แบ่ง partition ตามวัน** ด้วย pg_partman ลบข้อมูลครบ 30 วันด้วยการ drop partition ไม่ต้อง `DELETE` ทีละแถว
- ตารางหลัก: `sightings`, `journeys` (เส้นทางที่ Linker ต่อแล้ว; sighting แต่ละแถวเก็บ `journey_id` + วิธีต่อ: ชัด / ป้ายคล้าย / เดา + คะแนน), `cameras`, `users`, `sessions`, `audit_log`

**ที่เก็บภาพ**
- รุ่นแรกใช้ filesystem: `/data/images/YYYY-MM-DD/{camera_id}/{sighting_id}_{crop|context}.jpg`
- เข้าถึงผ่าน interface `ImageStore` เท่านั้น เพื่อย้ายไป S3 / SeaweedFS ภายหลังได้
- ลบตามรอบ 30 วันด้วยการลบทั้งโฟลเดอร์ของวันนั้น พร้อมกับ drop partition
- ไม่ใช้ MinIO เพราะเป็น AGPL และรุ่น community ถูกลดฟีเจอร์ลงตั้งแต่ปี 2025

**การเข้ารหัส**: ใช้ LUKS เข้ารหัสทั้งดิสก์ (ฐานข้อมูลและภาพ)

## 5. API และหน้าเว็บ

**API**: FastAPI + psycopg 3 (เขียน SQL ตรง เพราะคำค้นใช้ pg_trgm / pgvector ซึ่ง ORM ไม่ช่วยอะไร) ตอนนี้ schema อยู่ใน `deploy/db/init/` ภายหลังจะย้ายไปจัดการด้วย Alembic
- Auth ทำเองในตัว: argon2 + session cookie (HttpOnly, Secure) บทบาท `viewer` / `investigator` / `admin`
  - Keycloak ใหญ่เกินไปสำหรับตึกเดียว ถ้าภายหลังต้องเชื่อม SSO ขององค์กรค่อยเพิ่ม OIDC
- **Audit log**: ทุก endpoint ค้นหาผ่าน dependency ที่บันทึก log (ใคร ค้นอะไร เมื่อไร ได้ผลกี่รายการ) ก่อนคืนผล
  - role ของแอปถูก revoke สิทธิ์ `UPDATE` / `DELETE` บน `audit_log` จึงแก้ย้อนหลังไม่ได้
  - audit log ไม่อยู่ในรอบลบ 30 วัน (ระยะเก็บแยก รอเจ้าของระบบกำหนด)
- ภาพส่งผ่าน API ที่ตรวจสิทธิ์เท่านั้น ไม่เปิดโฟลเดอร์ภาพให้เข้าถึงตรง

**หน้าเว็บ**: React + Vite + TypeScript, TanStack Query, shadcn/ui หรือ Mantine
- หน้าค้นหา (ป้าย / เวลา / กล้อง / สี-ประเภท / อัปโหลดภาพ) → ไทม์ไลน์ต่อคัน พร้อมป้ายสถานะ ชัด / ป้ายคล้าย / เดา

**Reverse proxy**: Caddy (TLS อัตโนมัติ หรือใช้ cert ภายในองค์กร)

## 6. เครื่อง GPU ที่มี

เครื่องสำหรับเทรนและวัดความเร็ว (แยกจากเครื่องพัฒนาที่ไม่มี GPU):
- **RTX 4060 Laptop 8 GB** + i5-14450HX
- ผลต่อการเลือก
  - VRAM 8 GB พอสำหรับ fine-tune โมเดลขนาดเล็ก (RT-DETR-R18 / YOLOX-S, PARSeq, classifier) ต้องใช้ AMP (fp16) และ batch เล็ก
  - inference ใช้ TensorRT fp16 ส่วน DeepStream ยังไม่จำเป็น
  - มี NVDEC ตัวเดียว ต้องวัดจริงว่าถอดรหัสได้กี่สตรีม
- **ข้อควรระวังถ้าจะใช้เป็นเครื่องจริง**: โน้ตบุ๊กไม่ได้ออกแบบมาให้รัน 24 ชั่วโมงต่อเนื่อง (ความร้อน, GPU ลดความเร็วเมื่อร้อน, ไม่มีที่ใส่ดิสก์เพิ่ม) ใช้วัดความเป็นไปได้ในขั้นที่ 1 ได้ แต่ควรประเมินเครื่องสำหรับรันจริงจากตัวเลขที่วัดได้
- ขั้นตอนการเทรนอยู่ที่ [training/README.md](training/README.md)

## 7. การติดตั้งและเฝ้าระวัง

- **Ubuntu 24.04 LTS** + Docker Compose + NVIDIA Container Toolkit
  - พัฒนาบน Windows ได้ (WSL2) แต่เครื่องจริงควรเป็น Linux
- **Prometheus + Grafana** + DCGM exporter: GPU utilization, FPS ต่อกล้อง, ความยาวคิว, กล้องที่หลุด
- **pgBackRest** สำรองฐานข้อมูล (ข้อมูลสำรองก็ต้องลบตามรอบ 30 วันด้วย)

## 8. โครงสร้าง repo

```
flock/
  contracts/      # Sighting event schema + ตัวช่วยป้าย/จังหวัด (ใช้ร่วมกันทุกส่วน)
  training/       # ขั้นตอนและสคริปต์เทรน (รันบนเครื่อง GPU)
  vision/         # ingest, detector, tracker, readers (plugin)
  api/            # writer (คิว → DB), linker (ต่อเส้นทางข้ามกล้อง), Search API
  web/            # React
  deploy/         # docker-compose, schema ฐานข้อมูล, topology.toml (ผังกล้อง), Caddyfile, grafana dashboards
```

## 9. จุดที่ต่างจาก README ข้อ 8 เดิม

1. ระบุ detector เป็น RT-DETR / YOLOX แทน "ตระกูล YOLO" เพื่อตัดปัญหา AGPL ตั้งแต่ต้น
2. จังหวัดใช้ classifier แยก ไม่ให้ OCR อ่านเอง
3. แบ่ง partition ตามวัน เพื่อให้การลบตามรอบ 30 วันง่ายและเร็ว
4. ที่เก็บภาพเริ่มที่ filesystem ผ่าน interface ยังไม่ใช้ object storage
5. ระบุข้อห้ามเรื่อง dataset ของ ReID ที่จำกัดเฉพาะงานวิจัย

## 10. ยังต้องยืนยัน

- จำนวนกล้อง และเครื่องที่จะใช้รันจริง (โน้ตบุ๊ก RTX 4060 หรือเครื่องตั้งโต๊ะ/เซิร์ฟเวอร์)
- ระยะเก็บ audit log
- ต้องเชื่อมกับระบบ login ขององค์กร (SSO) หรือไม่
