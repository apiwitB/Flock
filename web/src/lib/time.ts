// เวลา: ผู้ใช้คิดเป็นเวลาไทย (Asia/Bangkok, UTC+7 ตลอดปี ไม่มี DST)
// ช่องกรอกเป็น datetime-local ("YYYY-MM-DDTHH:mm") ซึ่งตีความเป็นเวลาไทยเสมอ ไม่ขึ้นกับ timezone ของเครื่อง

export const BANGKOK_TZ = "Asia/Bangkok";
export const BANGKOK_OFFSET = "+07:00";
const BANGKOK_OFFSET_MS = 7 * 60 * 60 * 1000;
export const MAX_WINDOW_DAYS = 31;
const MAX_WINDOW_MS = MAX_WINDOW_DAYS * 24 * 60 * 60 * 1000;

const LOCAL_RE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?$/;

/** "2026-11-23T08:00" (เวลาไทย) → "2026-11-23T08:00:00+07:00" หรือ null ถ้ารูปแบบผิด */
export function localInputToIso(local: string): string | null {
  const m = LOCAL_RE.exec(local.trim());
  if (!m) return null;
  const [, y, mo, d, h, mi, s] = m;
  const month = Number(mo);
  const day = Number(d);
  const hour = Number(h);
  const minute = Number(mi);
  const second = s === undefined ? 0 : Number(s);
  if (month < 1 || month > 12 || day < 1 || hour > 23 || minute > 59 || second > 59) return null;
  // ตรวจวันที่มีจริง (เช่น 31 ก.พ. ไม่ผ่าน)
  const probe = new Date(Date.UTC(Number(y), month - 1, day));
  if (probe.getUTCMonth() !== month - 1 || probe.getUTCDate() !== day) return null;
  return `${y}-${mo}-${d}T${h}:${mi}:${String(second).padStart(2, "0")}${BANGKOK_OFFSET}`;
}

/** Date → ค่าสำหรับช่อง datetime-local ในเวลาไทย ("YYYY-MM-DDTHH:mm") */
export function dateToLocalInput(date: Date): string {
  return new Date(date.getTime() + BANGKOK_OFFSET_MS).toISOString().slice(0, 16);
}

/** ช่วงเวลาค่าเริ่ม: 24 ชม.ล่าสุด (ตรงกับค่าเริ่มของเซิร์ฟเวอร์) */
export function defaultRange(now: Date = new Date()): { from: string; to: string } {
  // ปัดเวลาสิ้นสุดขึ้นเป็นนาทีถัดไป เพื่อไม่ให้ตกรถที่เพิ่งเห็นในนาทีนี้
  const end = new Date(Math.ceil(now.getTime() / 60000) * 60000);
  return { from: dateToLocalInput(new Date(end.getTime() - 24 * 3600 * 1000)), to: dateToLocalInput(end) };
}

export type WindowResult = { ok: true; from: string; to: string } | { ok: false; error: string };

/** ตรวจช่วงเวลาจากช่องกรอก (เวลาไทย) ก่อนส่ง: ต้องครบ, from < to, กว้างไม่เกิน 31 วัน */
export function validateWindow(fromLocal: string, toLocal: string): WindowResult {
  if (!fromLocal || !toLocal) return { ok: false, error: "กรุณาระบุทั้งเวลาเริ่มและเวลาสิ้นสุด" };
  const from = localInputToIso(fromLocal);
  const to = localInputToIso(toLocal);
  if (!from) return { ok: false, error: "รูปแบบเวลาเริ่มไม่ถูกต้อง" };
  if (!to) return { ok: false, error: "รูปแบบเวลาสิ้นสุดไม่ถูกต้อง" };
  const span = Date.parse(to) - Date.parse(from);
  if (span <= 0) return { ok: false, error: "เวลาเริ่มต้องอยู่ก่อนเวลาสิ้นสุด" };
  if (span > MAX_WINDOW_MS) return { ok: false, error: `ช่วงเวลากว้างได้ไม่เกิน ${MAX_WINDOW_DAYS} วัน` };
  return { ok: true, from, to };
}

const dateTimeFmt = new Intl.DateTimeFormat("th-TH", {
  timeZone: BANGKOK_TZ,
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

const timeFmt = new Intl.DateTimeFormat("th-TH", {
  timeZone: BANGKOK_TZ,
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

/** แสดงวันเวลาเป็นเวลาไทย เช่น "23 พ.ย. 2569 08:00:00" */
export function formatDateTime(iso: string): string {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? iso : dateTimeFmt.format(t);
}

/** แสดงเฉพาะเวลา (เวลาไทย) */
export function formatTime(iso: string): string {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? iso : timeFmt.format(t);
}

/** ระยะเวลาเป็นภาษาไทย เช่น "1 ชม. 5 นาที", "45 วินาที" */
export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "-";
  const totalSec = Math.round(ms / 1000);
  const days = Math.floor(totalSec / 86400);
  const hours = Math.floor((totalSec % 86400) / 3600);
  const minutes = Math.floor((totalSec % 3600) / 60);
  const seconds = totalSec % 60;
  const parts: string[] = [];
  if (days) parts.push(`${days} วัน`);
  if (hours) parts.push(`${hours} ชม.`);
  if (minutes) parts.push(`${minutes} นาที`);
  if (!days && !hours && (seconds || parts.length === 0)) parts.push(`${seconds} วินาที`);
  return parts.join(" ");
}
