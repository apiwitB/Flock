# vision: อ่านภาพจากกล้อง → Sighting event

```
กล้อง (RTSP) → VideoSource → ตัวตรวจรถ → Tracker → ตัวตรวจป้าย + OCR → BestShotSelector → ImageStore + คิว
```

| โมดูล | ทำอะไร | สถานะ |
|---|---|---|
| `source.py` | รับ RTSP/ไฟล์ ลดเฟรมเรต ต่อใหม่เมื่อกล้องหลุด ไม่เขียนรหัสผ่านกล้องลง log | ✅ เทสต์แล้ว (ไฟล์วิดีโอ + กล้องจำลอง) |
| `tracker.py` | ติดตามรถในกล้องเดียว แบบ ByteTrack อย่างง่าย | ✅ เทสต์แล้ว |
| `bestshot.py` | รวมหลายเฟรมของ track เป็น 1 sighting: โหวตป้าย, เลือกภาพดีที่สุด | ✅ เทสต์แล้ว |
| `readers.py` | OCR + จังหวัด จากไฟล์ ONNX ที่ export จาก `training/` | ✅ เทสต์ด้วย session จำลอง · ⏳ ยังไม่เคยรันกับโมเดลจริง |
| `detectors.py` | RT-DETRv2 (Hugging Face) สำหรับตรวจรถและป้าย | ⏳ **ยังไม่ได้ทดสอบ** ต้องใช้เครื่อง GPU |
| `pipeline.py` | ประกอบทุกส่วนของกล้องหนึ่งตัว | ✅ เทสต์ครบวงจรด้วยภาพสังเคราะห์ และกับ stack จริง |
| `sink.py` | บันทึกภาพ JPEG (เขียนเสร็จก่อนส่ง event เสมอ) + ส่งเข้าคิว | ✅ เทสต์แล้ว |
| `main.py` | อ่านไฟล์ตั้งค่า รันหลายกล้องใน process เดียว | ⏳ ยังไม่ได้รัน (ต้องมีโมเดล) |

## หลักการสำคัญ

- **ส่ง event ครั้งเดียวต่อรถหนึ่งคันต่อกล้อง** ไม่ใช่ทุกเฟรม ส่งเมื่อ track จบ หรือเห็นมาแล้ว `emit_after_seconds` (รถจอดนิ่งในภาพจะไม่ถูกส่งซ้ำ)
- **โหวตป้ายจากทุกเฟรม** ถ่วงน้ำหนักด้วยความมั่นใจของ OCR ถ้าเฟรมต่างๆ อ่านไม่ตรงกัน ความมั่นใจที่รายงานจะต่ำลงเอง
- **ความมั่นใจของ OCR ต่อภาพ** ใช้ตัวอักษรที่ไม่แน่ใจที่สุด ไม่ใช่ค่าเฉลี่ย ข้อความที่ไม่ตรงรูปแบบป้ายมาตรฐานถูกลดความมั่นใจลงครึ่งหนึ่ง
- **คิวล่มไม่ทำให้ event หาย** event ที่ส่งไม่สำเร็จถูกเก็บไว้ส่งซ้ำ (สูงสุด 10,000 ต่อกล้อง เกินนี้ทิ้งตัวเก่าสุด)
- **เวลา** ใช้นาฬิกาของเครื่อง (UTC) ตอนรับเฟรม เครื่องต้องตั้ง NTP ให้ตรง เพราะ linker เทียบเวลาข้ามกล้อง
- **ประเภทรถ** มาจาก detector (car / truck / bus / motorcycle) ส่วนสีรถยังไม่มี (ROADMAP A5)
- **ยังไม่มี embedding** linker จึงต่อเส้นทางด้วยป้ายอย่างเดียว (ROADMAP A6)

## รันบนเครื่อง GPU

```bash
# ติดตั้งตาม training/README.md ขั้น 0 (torch รุ่น CUDA) แล้ว
pip install -e contracts -e "vision[gpu,test]"
cp vision/config.example.toml vision.toml   # แก้ชื่อกล้อง และ path ของโมเดล
export FLOCK_QUEUE_URL=redis://:<password>@<host>:6379/0
export FLOCK_CAM_G_ENTRY='rtsp://user:pass@10.0.0.11/stream1'
flock-vision --config vision.toml
```

- `image_root` ต้องเป็นที่เดียวกับที่ api อ่านภาพ (volume `images` ใน compose)
- ทุก `id` ของกล้องต้องลงทะเบียนในตาราง `cameras` ก่อน ไม่อย่างนั้น writer จะย้าย event ไป dead-letter (`unknown_camera`)
- ลองกับคลิปที่บันทึกไว้ได้ ใส่ `url = "/clips/..."` และ `live = false` ในไฟล์ตั้งค่า
- ถ้ายังไม่มีโมเดลป้าย (ปิด `plate_detector` / `plate_ocr` ไว้) ระบบยังทำงานได้ แต่ event จะไม่มีป้าย

## เทสต์ (ไม่ต้องใช้ GPU)

```powershell
docker run --rm -v D:/Flock:/work -w /work/vision python:3.12-slim sh -c "pip install -q -e ../contracts -e '.[test]' && pytest -q"
```

## ยังไม่ได้ทำ (ROADMAP B)

- ทดสอบ `HFDetector` กับโมเดลจริง และเปลี่ยนเป็น TensorRT
- รวม batch ข้ามกล้องให้ใช้ GPU คุ้มขึ้น (ตอนนี้ใช้ lock ทีละเฟรม)
- ถอดรหัสบน GPU (NVDEC) ถ้าวัดแล้วว่า CPU เป็นคอขวด
- รายงานสถานะกล้อง (หลุด/ต่อได้) ให้ระบบเฝ้าระวัง (ROADMAP C7)
- จูน `fps`, `emit_after_seconds`, `plate_min_width` กับกล้องจริง
