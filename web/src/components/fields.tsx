import { useQuery } from "@tanstack/react-query";
import { useId, useMemo } from "react";
import { api } from "../api/client";
import type { Camera } from "../api/types";

/** รายชื่อกล้อง; ถ้า endpoint ยังไม่มี (404) หรือผิดพลาด คืน error และหน้าใช้ช่องพิมพ์แทน */
export function useCameras() {
  return useQuery({
    queryKey: ["cameras"],
    queryFn: ({ signal }) => api.cameras(signal),
    retry: false,
    staleTime: 5 * 60 * 1000,
  });
}

/** ชื่อกล้องสำหรับแสดงผล: ใช้ชื่อถ้ามี ไม่งั้นใช้รหัส */
export function useCameraName(): (id: string) => string {
  const { data } = useCameras();
  const map = useMemo(() => new Map((data ?? []).map((c: Camera) => [c.camera_id, c])), [data]);
  return (id: string) => {
    const c = map.get(id);
    if (!c?.name) return id;
    return c.name === id ? id : `${c.name} (${id})`;
  };
}

export function CameraField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const id = useId();
  const { data, isError, isPending } = useCameras();
  if (isError || (!isPending && (!data || data.length === 0))) {
    return (
      <div className="field">
        <label htmlFor={id}>รหัสกล้อง</label>
        <input id={id} type="text" value={value} onChange={(e) => onChange(e.target.value)} placeholder="ทุกกล้อง" autoComplete="off" spellCheck={false} />
        <small className="hint">โหลดรายชื่อกล้องไม่ได้ พิมพ์รหัสกล้องเอง หรือเว้นว่างเพื่อค้นทุกกล้อง</small>
      </div>
    );
  }
  return (
    <div className="field">
      <label htmlFor={id}>กล้อง</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} disabled={isPending}>
        <option value="">{isPending ? "กำลังโหลด…" : "ทุกกล้อง"}</option>
        {(data ?? []).map((c) => (
          <option key={c.camera_id} value={c.camera_id}>
            {c.name && c.name !== c.camera_id ? `${c.name} (${c.camera_id})` : c.camera_id}
            {c.location ? ` — ${c.location}` : ""}
          </option>
        ))}
      </select>
    </div>
  );
}

export function TimeRangeFields({
  from,
  to,
  onChange,
}: {
  from: string;
  to: string;
  onChange: (range: { from: string; to: string }) => void;
}) {
  const fromId = useId();
  const toId = useId();
  return (
    <fieldset className="time-range">
      <legend>ช่วงเวลา (เวลาไทย, ไม่เกิน 31 วัน)</legend>
      <div className="field">
        <label htmlFor={fromId}>ตั้งแต่</label>
        <input id={fromId} type="datetime-local" value={from} required onChange={(e) => onChange({ from: e.target.value, to })} />
      </div>
      <div className="field">
        <label htmlFor={toId}>ถึง</label>
        <input id={toId} type="datetime-local" value={to} required onChange={(e) => onChange({ from, to: e.target.value })} />
      </div>
    </fieldset>
  );
}

export const LIMIT_OPTIONS = [50, 100, 200, 500] as const;

export function LimitField({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>จำนวนผลสูงสุด</label>
      <select id={id} value={value} onChange={(e) => onChange(Number(e.target.value))}>
        {LIMIT_OPTIONS.map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
      </select>
    </div>
  );
}

/** สรุปจำนวนผล (aria-live) พร้อมเตือนเมื่อชนเพดาน */
export function ResultCount({ count, limit }: { count: number; limit: number }) {
  return (
    <p className="result-count" role="status" aria-live="polite">
      พบ {count.toLocaleString("th-TH")} รายการ
      {count >= limit ? ` (แสดงสูงสุด ${limit} รายการ อาจมีมากกว่านี้ ลองแคบช่วงเวลาหรือเพิ่มเงื่อนไข)` : ""}
    </p>
  );
}

export function PlateText({ text, province }: { text: string | null; province?: string | null }) {
  if (!text) return <span className="muted">อ่านป้ายไม่ได้</span>;
  return (
    <span className="plate">
      <span className="plate__text">{text}</span>
      {province ? <span className="plate__province">{province}</span> : null}
    </span>
  );
}
