# ขั้นตอนการเทรน (ขั้นที่ 1: ทดสอบความเป็นไปได้)

เป้าหมายของขั้นนี้ (README หลัก ข้อ 11): **วัดความแม่นยำการอ่านป้ายและความเร็วบน GPU จริง**
จากภาพของกล้องในอาคาร ก่อนจะลงมือสร้างระบบเต็ม

| ขั้น | ทำที่ไหน | ใช้ GPU |
|---|---|---|
| A. บันทึกคลิปจากกล้อง | เครื่องใดก็ได้ในเครือข่ายกล้อง | ไม่ |
| B. ดึงเฟรม → label ใน CVAT → แปลงเป็นชุดข้อมูล | เครื่องใดก็ได้ | ไม่ |
| C. เทรน 3 โมเดล | **เครื่อง RTX 4060** | ใช่ |
| D. วัดผล + export ONNX/TensorRT + วัดความเร็ว | **เครื่อง RTX 4060** | ใช่ |

## โมเดลที่เทรน

| โมเดล | ทำอะไร | สคริปต์ | หมายเหตุ |
|---|---|---|---|
| ตัวตรวจรถ | หา car/motorcycle/bus/truck | (ไม่เทรน) | ใช้ weights COCO ของ RT-DETRv2 สำเร็จรูป |
| ตัวตรวจป้าย | หากรอบป้ายในภาพเต็ม | `flock_train.detector` | RT-DETRv2-R18 fine-tune, 1 คลาส |
| OCR | อ่านบรรทัดเลขทะเบียน | `flock_train.ocr` | CRNN + CTC เขียนเอง ไม่พึ่ง repo ภายนอก |
| จังหวัด | จำแนกบรรทัดล่าง 78 คลาส | `flock_train.province` | timm ResNet-18 |

ชุดตัวอักษรของ OCR และลำดับจังหวัดอยู่ใน `contracts/` ที่เดียว ทั้งตอนเทรนและตอนใช้งานจริงต้องใช้ค่าชุดเดียวกัน

## สถานะการทดสอบ

| ส่วน | ทดสอบแล้ว |
|---|---|
| `cvat_convert`, `eval_ocr`, ชื่อไฟล์และการแบ่งชุด | เทสต์ผ่านบน CPU |
| `ocr` train + export ONNX (batch > 1 ให้ผลตรงกับ PyTorch) | รันเทรนสั้นบน CPU ด้วยภาพสุ่ม ผ่าน |
| `province` train + export ONNX | รันเทรนสั้นบน CPU ด้วยภาพสุ่ม ผ่าน |
| `detector` | **ยังไม่ได้รัน** ต้องดาวน์โหลด weights และใช้ GPU ให้รันเป็นอย่างแรกบนเครื่อง 4060 |
| `extract_frames` | ยังไม่ได้รันกับคลิปจริง |

---

## 0. เตรียมเครื่อง RTX 4060

แนะนำ **Ubuntu 24.04** ถ้าใช้ Windows ให้รันผ่าน **WSL2** (ไดรเวอร์ NVIDIA ติดตั้งฝั่ง Windows เท่านั้น ห้ามติดตั้งใน WSL)

```bash
# 1) ไดรเวอร์ NVIDIA รุ่นล่าสุด แล้วตรวจ
nvidia-smi

# 2) Python 3.12 + venv
sudo apt install -y python3.12-venv ffmpeg
python3.12 -m venv ~/flock-venv && source ~/flock-venv/bin/activate

# 3) PyTorch รุ่น CUDA (ตรวจคำสั่งล่าสุดที่ pytorch.org ถ้า cu128 ไม่มีแล้ว)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 4) โค้ดโปรเจกต์
cd flock
pip install -e contracts -e "training[gpu,test]" onnxruntime-gpu

# 5) ตรวจ
python -m flock_train.check_env
pytest -q training contracts
```

ข้อควรระวังเรื่องโน้ตบุ๊ก: เสียบสายชาร์จ ตั้งโหมดพลังงานสูงสุด และดูอุณหภูมิด้วย `nvidia-smi -l 5` ระหว่างเทรน
ถ้า GPU ร้อนจนลดความเร็ว ตัวเลขที่วัดในขั้น D จะต่ำกว่าความจริง

## A. บันทึกคลิปจากกล้อง

ตั้งชื่อกล้องให้คงที่ (เช่น `B1-ramp-up`, `L2-north`) ชื่อนี้จะเป็น `camera_id` ไปตลอด

```bash
ffmpeg -rtsp_transport tcp -i "rtsp://<user>:<pass>@<ip>/<path>" \
  -c copy -f segment -segment_time 600 -reset_timestamps 1 -strftime 1 \
  "clips/B1-ramp-up_%Y%m%dT%H%M%S.mp4"
```

ช่วงเวลาที่ต้องมีให้ครบ เพราะความแม่นยำตอนกลางคืนคือความเสี่ยงหลัก (README ข้อ 10):
- เช้า, เที่ยง, เย็น, **กลางคืน**, **ไฟหน้ารถส่องเข้ากล้อง**, ฝนตก (ถ้ามีหลังคาไม่โดน ข้ามได้)
- อย่างน้อย 2 วัน และถ้าทำได้ควรมีกล้องมากกว่า 1 จุด เพราะชุด val/test แบ่งตามกล้องและชั่วโมง

> คลิปพวกนี้เป็นข้อมูลส่วนบุคคล (PDPA) เก็บในดิสก์ที่เข้ารหัส อย่าอัปโหลดขึ้นคลาวด์ และลบเมื่อจบขั้นทดสอบ

## B. ดึงเฟรม → label → แปลงชุดข้อมูล

```bash
python -m flock_train.extract_frames clips/*.mp4 --out frames --every 1.0
```

**ตั้งค่า CVAT** (รันเองในเครื่องด้วย Docker ตามคู่มือของ CVAT) สร้าง label เดียวชื่อ `plate` แบบ rectangle มี attribute:

| attribute | ชนิด | ค่า |
|---|---|---|
| `text` | text | เลขทะเบียนบรรทัดบน ไม่ต้องเว้นวรรค เช่น `1กข1234` |
| `province` | text | ชื่อจังหวัดเต็ม หรือ `กทม` (แปลงให้อัตโนมัติ) |
| `readable` | checkbox (ค่าเริ่ม true) | ไม่ติ๊กถ้าคนยังอ่านไม่ออก (ยังใช้เทรนตัวตรวจป้ายได้) |
| `plate_type` | select: `car`, `motorcycle`, `other` | รุ่นแรกเทรน OCR เฉพาะ `car` |

กฎการ label:
- ตีกรอบ **ทุกป้ายที่เห็น** แม้อ่านไม่ออก ถ้าไม่ตีกรอบ ตัวตรวจจะเรียนว่าตรงนั้นไม่ใช่ป้าย
- กรอบชิดขอบป้าย ไม่เผื่อ
- ปริมาณขั้นต่ำที่ควรมีก่อนเทรนครั้งแรก: ป้ายที่อ่านออก **~2,000 ป้าย** (ยิ่งหลากหลายตัวอักษรยิ่งดี)

Export เป็น **"CVAT for images 1.1"** แล้วแปลง:

```bash
python -m flock_train.cvat_convert annotations.xml --images frames --out datasets/v1
```

ดู `datasets/v1/report.json` ก่อนเทรนทุกครั้ง:
- `rejected.text_non_standard` / `text_bad_char` สูง → label ผิดรูปแบบ แก้ใน CVAT
- ชุด `val` หรือ `test` ว่าง → ข้อมูลมาจากกล้อง/ชั่วโมงน้อยเกินไป
- เปิดภาพใน `ocr/train/images` ดูสัก 20 ภาพ ว่าตัดได้เฉพาะบรรทัดเลขทะเบียนจริง
  ถ้าตัดเกินหรือขาด ปรับ `--text-split` (ค่าเริ่ม 0.62 คือ 62% บนของความสูงป้าย)

## C. เทรน (เครื่อง 4060)

ลำดับแนะนำ: OCR ก่อน (เล็กและเร็ว ได้คำตอบเรื่องความเป็นไปได้เร็วที่สุด) แล้วจึงจังหวัด และตัวตรวจป้าย

```bash
python -m flock_train.ocr train      --data datasets/v1/ocr      --out runs/ocr-v1
python -m flock_train.province train --data datasets/v1/province --out runs/province-v1
python -m flock_train.detector train --data datasets/v1/det      --out runs/det-v1 --batch 4
```

| โมเดล | ค่าเริ่มที่ควรพอดี 8 GB | ถ้า out of memory |
|---|---|---|
| OCR | `--batch 128` | ลดเป็น 64 |
| จังหวัด | `--batch 128` | ลดเป็น 64 |
| ตัวตรวจป้าย | `--batch 4 --size 640` | `--batch 2` |

ทุกโมเดลใช้ AMP (fp16) อัตโนมัติเมื่อมี GPU ผลแต่ละรอบอยู่ใน `runs/*/history.json`

ห้ามแก้ `OCR_CHARSET` หรือลำดับ `PROVINCES` ใน `contracts/` หลังเทรนแล้ว ถ้าแก้ checkpoint เดิมจะใช้ไม่ได้
คำสั่ง export จะตรวจและแจ้ง error ให้

## D. วัดผลและความเร็ว

```bash
# ความแม่นยำ OCR บนชุด test + คู่ตัวอักษรที่สลับกันบ่อย
python -m flock_train.eval_ocr runs/ocr-v1/test_predictions.tsv --out runs/ocr-v1/eval.json

# export ONNX
python -m flock_train.ocr export      --ckpt runs/ocr-v1/best.pt      --out runs/ocr-v1/plate_ocr.onnx
python -m flock_train.province export --ckpt runs/province-v1/best.pt --out runs/province-v1/province.onnx

# วัดความเร็ว TensorRT fp16 (trtexec มากับ TensorRT)
trtexec --onnx=runs/ocr-v1/plate_ocr.onnx --fp16 \
  --minShapes=image:1x3x48x160 --optShapes=image:16x3x48x160 --maxShapes=image:64x3x48x160
```

ตัวตรวจป้าย: ยังไม่มีคำสั่ง export ONNX ในรุ่นนี้ ให้วัดความเร็วด้วย PyTorch fp16 ไปก่อน แล้วค่อยเพิ่ม export หลังสคริปต์เทรนรันผ่าน

**สิ่งที่ต้องนำกลับมา** (ใช้ตัดสินใจขั้นต่อไป):
1. `eval.json`: exact match และ CER **แยกกลางวัน/กลางคืน** (กรองจากชื่อไฟล์ตามชั่วโมง)
2. คู่ตัวอักษรที่สลับบ่อย ใช้แทนค่าเดาใน `contracts/flock_contracts/plates.py` → `CONFUSABLE_PAIRS`
3. ความเร็ว: ms ต่อภาพของแต่ละโมเดล, จำนวนสตรีม 1080p ที่ NVDEC ถอดรหัสได้, อุณหภูมิ GPU ระหว่างรันต่อเนื่อง 30 นาที
4. `history.json` ของทุกโมเดล
