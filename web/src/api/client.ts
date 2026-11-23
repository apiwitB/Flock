import type { BrowseParams, Camera, Journey, PlateMatch, PlateSearchParams, Sighting, User } from "./types";

/** ข้อผิดพลาดจาก API ทุกแบบ: status = 0 หมายถึงติดต่อเซิร์ฟเวอร์ไม่ได้ */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/** 401: ยังไม่ได้เข้าสู่ระบบ หรือ session หมดอายุ */
export class UnauthorizedError extends ApiError {
  constructor(detail?: unknown) {
    super(401, "กรุณาเข้าสู่ระบบ", detail);
    this.name = "UnauthorizedError";
  }
}

/** 403: บทบาทของผู้ใช้ไม่พอ */
export class ForbiddenError extends ApiError {
  constructor(detail?: unknown) {
    super(403, "บัญชีของคุณไม่มีสิทธิ์ใช้งานส่วนนี้", detail);
    this.name = "ForbiddenError";
  }
}

export class NotFoundError extends ApiError {
  constructor(detail?: unknown) {
    super(404, "ไม่พบข้อมูล", detail);
    this.name = "NotFoundError";
  }
}

export class ValidationError extends ApiError {
  constructor(message: string, detail?: unknown) {
    super(422, message, detail);
    this.name = "ValidationError";
  }
}

type UnauthorizedHandler = () => void;
let onUnauthorized: UnauthorizedHandler | null = null;

/** ตั้งตัวรับสัญญาณ 401 (แอปใช้เพื่อพาผู้ใช้ไปหน้าเข้าสู่ระบบ) คืนฟังก์ชันยกเลิก */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): () => void {
  onUnauthorized = handler;
  return () => {
    if (onUnauthorized === handler) onUnauthorized = null;
  };
}

const FIELD_LABELS: Record<string, string> = {
  q: "เลขป้าย",
  from: "เวลาเริ่ม",
  to: "เวลาสิ้นสุด",
  max_distance: "ระยะต่างของป้าย",
  limit: "จำนวนผลลัพธ์",
  camera_id: "กล้อง",
  province: "จังหวัด",
  journey_id: "หมายเลขเส้นทาง",
  username: "ชื่อผู้ใช้",
  password: "รหัสผ่าน",
};

/** แปลง detail ของ 422 เป็นข้อความภาษาไทย */
export function validationMessage(detail: unknown): string {
  if (typeof detail === "string") {
    if (detail.startsWith("unknown province:")) {
      return `ไม่รู้จักจังหวัด "${detail.slice("unknown province:".length).trim()}"`;
    }
    if (detail.includes("'from' must be before 'to'")) return "เวลาเริ่มต้องอยู่ก่อนเวลาสิ้นสุด";
    if (detail.startsWith("time window must be at most")) return "ช่วงเวลากว้างได้ไม่เกิน 31 วัน";
    return `ข้อมูลไม่ถูกต้อง: ${detail}`;
  }
  if (Array.isArray(detail) && detail.length > 0) {
    const parts = detail.map((d: unknown) => {
      const item = (d ?? {}) as { loc?: unknown; msg?: unknown };
      const loc = Array.isArray(item.loc) ? item.loc : [];
      const field = loc.length > 0 ? String(loc[loc.length - 1]) : "";
      const label = FIELD_LABELS[field] ?? field;
      const msg = typeof item.msg === "string" ? item.msg : "ไม่ถูกต้อง";
      return label ? `${label}: ${msg}` : msg;
    });
    return `ข้อมูลไม่ถูกต้อง (${parts.join("; ")})`;
  }
  return "ข้อมูลไม่ถูกต้อง";
}

export interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  /** false = ไม่ส่งสัญญาณ 401 ไปยังแอป (หน้าเข้าสู่ระบบ: 401 แปลว่ารหัสผิด) */
  signalUnauthorized?: boolean;
  signal?: AbortSignal | undefined;
}

async function readDetail(res: Response): Promise<unknown> {
  try {
    const data: unknown = await res.json();
    if (data && typeof data === "object" && "detail" in data) return (data as { detail: unknown }).detail;
    return data;
  } catch {
    return undefined;
  }
}

/** แปลง response ที่ไม่สำเร็จเป็น error ตามประเภท และส่งสัญญาณเมื่อได้ 401 */
export async function errorFor(res: Response, signalUnauthorized = true): Promise<ApiError> {
  const detail = await readDetail(res);
  switch (res.status) {
    case 401:
      if (signalUnauthorized) onUnauthorized?.();
      return new UnauthorizedError(detail);
    case 403:
      return new ForbiddenError(detail);
    case 404:
      return new NotFoundError(detail);
    case 422:
      return new ValidationError(validationMessage(detail), detail);
    default:
      return new ApiError(res.status, `เซิร์ฟเวอร์ตอบผิดพลาด (${res.status})`, detail);
  }
}

function isAbort(e: unknown): boolean {
  return typeof e === "object" && e !== null && (e as { name?: unknown }).name === "AbortError";
}

/** เรียก API ด้วย URL แบบ relative เท่านั้น (same-origin, ใช้ cookie) */
export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  if (!path.startsWith("/") || path.startsWith("//")) throw new ApiError(0, "URL ไม่ถูกต้อง");
  const headers: Record<string, string> = { Accept: "application/json" };
  const init: RequestInit = { method: opts.method ?? "GET", credentials: "same-origin", headers };
  if (opts.signal) init.signal = opts.signal;
  if (opts.body !== undefined) {
    init.body = JSON.stringify(opts.body);
    headers["Content-Type"] = "application/json";
  }
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch (e) {
    if (isAbort(e)) throw e;
    throw new ApiError(0, "ติดต่อเซิร์ฟเวอร์ไม่ได้ ตรวจสอบการเชื่อมต่อเครือข่าย");
  }
  if (!res.ok) throw await errorFor(res, opts.signalUnauthorized ?? true);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** สร้าง query string โดยข้ามค่าว่าง */
export function buildQuery(params: object): string {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    usp.set(k, String(v));
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  login: (username: string, password: string) =>
    request<User>("/auth/login", { method: "POST", body: { username, password }, signalUnauthorized: false }),
  logout: () => request<void>("/auth/logout", { method: "POST", signalUnauthorized: false }),
  /** คืน null ถ้ายังไม่ได้เข้าสู่ระบบ */
  me: async (): Promise<User | null> => {
    try {
      return await request<User>("/auth/me", { signalUnauthorized: false });
    } catch (e) {
      if (e instanceof UnauthorizedError) return null;
      throw e;
    }
  },
  cameras: (signal?: AbortSignal) => request<Camera[]>("/cameras", { signal }),
  searchPlates: (p: PlateSearchParams, signal?: AbortSignal) =>
    request<PlateMatch[]>(`/search/plates${buildQuery(p)}`, { signal }),
  sightings: (p: BrowseParams, signal?: AbortSignal) =>
    request<Sighting[]>(`/sightings${buildQuery(p)}`, { signal }),
  journey: (id: number, signal?: AbortSignal) => request<Journey>(`/journeys/${id}`, { signal }),
  /** โหลดภาพเป็น blob (ทุกครั้งถูกบันทึกใน audit log ฝั่งเซิร์ฟเวอร์) */
  image: async (url: string, signal?: AbortSignal): Promise<Blob> => {
    if (!url.startsWith("/") || url.startsWith("//")) throw new ApiError(0, "URL ภาพไม่ถูกต้อง");
    const init: RequestInit = { credentials: "same-origin" };
    if (signal) init.signal = signal;
    let res: Response;
    try {
      res = await fetch(url, init);
    } catch (e) {
      if (isAbort(e)) throw e;
      throw new ApiError(0, "ติดต่อเซิร์ฟเวอร์ไม่ได้");
    }
    if (!res.ok) throw await errorFor(res);
    return res.blob();
  },
};
