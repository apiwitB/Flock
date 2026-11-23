import { formatPercent } from "./confidence";

// ค่าลักษณะรถที่ Reader ส่งมาเป็นภาษาอังกฤษ (เช่น "white", "sedan") แสดงเป็นภาษาไทยเมื่อรู้จัก
// ค่าที่ไม่รู้จักแสดงตามที่ได้รับ; ตัวกรองส่งค่าภาษาอังกฤษไปยัง API ตามเดิม

export const COLOR_LABELS: Record<string, string> = {
  white: "ขาว",
  black: "ดำ",
  gray: "เทา",
  grey: "เทา",
  silver: "เงิน",
  red: "แดง",
  blue: "น้ำเงิน",
  green: "เขียว",
  yellow: "เหลือง",
  orange: "ส้ม",
  brown: "น้ำตาล",
  gold: "ทอง",
  beige: "เบจ",
  purple: "ม่วง",
  pink: "ชมพู",
};

export const VEHICLE_TYPE_LABELS: Record<string, string> = {
  sedan: "เก๋ง",
  hatchback: "แฮทช์แบ็ก",
  suv: "SUV",
  pickup: "กระบะ",
  van: "รถตู้",
  truck: "รถบรรทุก",
  bus: "รถบัส",
  motorcycle: "จักรยานยนต์",
  car: "รถยนต์",
};

export const ATTRIBUTE_NAMES: Record<string, string> = {
  color: "สี",
  vehicle_type: "ประเภท",
  make: "ยี่ห้อ",
  model: "รุ่น",
};

const VALUE_LABELS: Record<string, Record<string, string>> = {
  color: COLOR_LABELS,
  vehicle_type: VEHICLE_TYPE_LABELS,
};

export function valueLabel(name: string, value: string): string {
  return VALUE_LABELS[name]?.[value.toLowerCase()] ?? value;
}

export interface AttributeRow {
  name: string;
  label: string;
  value: string;
  confidence: string | null;
}

/** attributes ของ sighting → รายการที่แสดงได้ เรียง สี ประเภท ยี่ห้อ รุ่น ก่อน */
export function attributeRows(attributes: Record<string, unknown> | null | undefined): AttributeRow[] {
  if (!attributes) return [];
  const order = Object.keys(ATTRIBUTE_NAMES);
  const rows: AttributeRow[] = [];
  for (const [name, raw] of Object.entries(attributes)) {
    let value: string | null = null;
    let confidence: number | null = null;
    if (raw && typeof raw === "object" && "value" in raw) {
      const v = (raw as { value: unknown }).value;
      if (v !== null && v !== undefined && v !== "") value = String(v);
      const c = (raw as { confidence?: unknown }).confidence;
      if (typeof c === "number") confidence = c;
    } else if (typeof raw === "string" || typeof raw === "number") {
      value = String(raw);
    }
    if (value === null) continue;
    rows.push({ name, label: ATTRIBUTE_NAMES[name] ?? name, value: valueLabel(name, value), confidence: formatPercent(confidence) });
  }
  const rank = (n: string) => (order.indexOf(n) === -1 ? order.length : order.indexOf(n));
  return rows.sort((a, b) => rank(a.name) - rank(b.name) || a.name.localeCompare(b.name));
}

/** ข้อความสั้นสำหรับตาราง เช่น "ขาว (81%) · เก๋ง (70%)" */
export function attributeSummary(attributes: Record<string, unknown> | null | undefined, names = ["color", "vehicle_type"]): string {
  const rows = attributeRows(attributes).filter((r) => names.includes(r.name));
  if (rows.length === 0) return "-";
  return rows.map((r) => (r.confidence ? `${r.value} (${r.confidence})` : r.value)).join(" · ");
}
