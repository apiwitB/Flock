// ภาษาแสดงระดับความมั่นใจ: ที่เดียวในแอปที่แปลงสถานะการต่อ/การจับคู่ เป็นป้ายภาษาไทยและสี
// หลักของผลิตภัณฑ์: ระบบต้องไม่ดูแน่ใจเมื่อกำลังเดา สีของ "เดา" ต้องไม่เหมือน "ชัด" เด็ดขาด

/** tone ใช้เป็น class CSS: badge--<tone> */
export type Tone = "exact" | "similar" | "guess" | "partial" | "start" | "unknown";

export interface BadgeInfo {
  /** ข้อความบนป้าย */
  label: string;
  tone: Tone;
  /** สัญลักษณ์ประกอบ (ไม่พึ่งสีอย่างเดียว) */
  symbol: string;
  /** คำอธิบายภาษาไทย ใช้ใน title/คำอธิบายป้าย */
  description: string;
  /** คะแนนเป็นข้อความ เช่น "87%" หรือ null ถ้าไม่มีคะแนน */
  scoreText: string | null;
}

/** สถานะที่รับได้: link_method ของ journey และ match ของการค้นป้าย */
export type ConfidenceKind = "exact" | "similar" | "similar_plate" | "guess" | "partial" | "new";

interface Def {
  label: string;
  tone: Tone;
  symbol: string;
  description: string;
}

const DEFS: Record<ConfidenceKind, Def> = {
  exact: {
    label: "ชัด",
    tone: "exact",
    symbol: "✓",
    description: "เลขป้ายตรงกันทุกตัว",
  },
  similar: {
    label: "ป้ายคล้าย",
    tone: "similar",
    symbol: "≈",
    description: "เลขป้ายต่างกันเล็กน้อย (อาจเป็น OCR อ่านผิด 1–2 ตัว) ควรดูภาพยืนยัน",
  },
  similar_plate: {
    label: "ป้ายคล้าย",
    tone: "similar",
    symbol: "≈",
    description: "ต่อด้วยเลขป้ายที่ใกล้เคียงกัน (ไม่ตรงทุกตัว) และสี/ประเภทรถไม่ขัดกัน ควรดูภาพยืนยัน",
  },
  guess: {
    label: "เดา",
    tone: "guess",
    symbol: "?",
    description: "ไม่มีป้ายให้เทียบ ระบบเดาจากลักษณะรถ กล้องที่อยู่ติดกัน และเวลา อาจไม่ใช่คันเดียวกัน",
  },
  partial: {
    label: "ตรงบางส่วน",
    tone: "partial",
    symbol: "◐",
    description: "คำค้นตรงกับเพียงบางส่วนของเลขป้าย",
  },
  new: {
    label: "จุดเริ่ม",
    tone: "start",
    symbol: "●",
    description: "จุดแรกที่เห็นรถคันนี้ในเส้นทาง (ไม่ได้ต่อจากจุดก่อนหน้า)",
  },
};

const UNKNOWN: Def = {
  label: "ไม่ทราบ",
  tone: "unknown",
  symbol: "–",
  description: "ยังไม่ได้ต่อเข้ากับเส้นทาง หรือไม่ทราบวิธีต่อ",
};

/** คะแนน 0..1 → "87%" (ปัดลง เพื่อไม่ให้ดูมั่นใจเกินจริง เช่น 0.996 → 99% ไม่ใช่ 100%) */
export function formatPercent(score: number | null | undefined): string | null {
  if (score === null || score === undefined || !Number.isFinite(score)) return null;
  const clamped = Math.min(1, Math.max(0, score));
  return `${Math.floor(clamped * 100)}%`;
}

export function isConfidenceKind(kind: unknown): kind is ConfidenceKind {
  return typeof kind === "string" && Object.prototype.hasOwnProperty.call(DEFS, kind);
}

/** แปลงสถานะ + คะแนน เป็นข้อมูลป้าย; "new" ไม่มีคะแนนให้แสดง */
export function badgeFor(kind: string | null | undefined, score?: number | null): BadgeInfo {
  const def = isConfidenceKind(kind) ? DEFS[kind] : UNKNOWN;
  const pct = def.tone === "start" || def.tone === "unknown" ? null : formatPercent(score);
  // คะแนนของ "เดา" คือความคล้ายของลักษณะรถ ไม่ใช่ความมั่นใจว่าเป็นคันเดียวกัน
  // จึงต้องบอกให้ชัด ไม่อย่างนั้น "เดา 100%" จะอ่านเหมือนแน่ใจ
  const scoreText = pct !== null && def.tone === "guess" ? `ลักษณะคล้าย ${pct}` : pct;
  return { ...def, scoreText };
}

/** ข้อความเต็มสำหรับโปรแกรมอ่านหน้าจอ เช่น "เดา 62%: ไม่มีป้ายให้เทียบ ..." */
export function badgeAccessibleText(info: BadgeInfo): string {
  return `${info.label}${info.scoreText ? ` ${info.scoreText}` : ""}: ${info.description}`;
}

/** ระยะต่างของป้าย (API: ตัวที่หน้าตาคล้ายกัน เช่น ข/ช นับ 0.4 ตัวอื่นนับ 1) เป็นข้อความที่คนอ่านเข้าใจ */
export function describeDistance(distance: number): string {
  if (distance <= 0) return "ตรงทุกตัว";
  if (distance < 1) return "ต่างเฉพาะตัวที่หน้าตาคล้ายกัน (เช่น ข/ช)";
  if (Number.isInteger(distance)) return `ต่าง ${distance} ตัว`;
  return `ต่าง ${Math.floor(distance)} ตัว + ตัวที่หน้าตาคล้ายกัน`;
}

/** คำอธิบายป้ายสำหรับหน้าค้นหาป้าย */
export const MATCH_LEGEND: ConfidenceKind[] = ["exact", "similar", "partial"];
/** คำอธิบายป้ายสำหรับหน้าเส้นทาง */
export const LINK_LEGEND: ConfidenceKind[] = ["new", "exact", "similar_plate", "guess"];

/** weakest_link ที่ต้องเตือนว่าเส้นทางบางช่วงเป็นการอนุมาน */
export function isUncertainLink(weakest: string | null | undefined): boolean {
  return weakest === "guess" || weakest === "similar_plate";
}
