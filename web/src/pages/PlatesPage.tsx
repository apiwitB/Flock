import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { PlateMatch } from "../api/types";
import { BadgeLegend, ConfidenceBadge } from "../components/Badge";
import { ErrorMessage } from "../components/ErrorMessage";
import { CameraField, LimitField, PlateText, ResultCount, TimeRangeFields, useCameraName } from "../components/fields";
import { SightingImage } from "../components/SightingImage";
import { describeDistance, formatPercent, MATCH_LEGEND } from "../lib/confidence";
import { formatDateTime, validateWindow } from "../lib/time";
import { useSearchState } from "../searchState";

const DISTANCE_HELP: Record<number, string> = {
  0: "0 = ตรงทุกตัวเท่านั้น",
  1: "1 = ยอมให้ต่างได้ 1 ตัว",
  2: "2 = ยอมให้ต่างได้ 2 ตัว (ค่าเริ่ม)",
  3: "3 = ยอมให้ต่างได้ 3 ตัว (ผลคลาดเคลื่อนมากขึ้น)",
};

export function PlatesPage() {
  const { plateForm: form, setPlateForm: setForm, plateQuery: query, setPlateQuery: setQuery } = useSearchState();
  const [formError, setFormError] = useState<string | null>(null);

  const result = useQuery({
    queryKey: ["plates", query],
    queryFn: ({ signal }) => api.searchPlates(query!, signal),
    enabled: query !== null,
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 30_000,
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const q = form.q.trim();
    if (!q) return setFormError("กรุณากรอกเลขป้าย");
    if (q.length > 16) return setFormError("เลขป้ายยาวได้ไม่เกิน 16 ตัวอักษร");
    const w = validateWindow(form.from, form.to);
    if (!w.ok) return setFormError(w.error);
    setFormError(null);
    const next = {
      q,
      from: w.from,
      to: w.to,
      camera_id: form.camera_id.trim() || undefined,
      province: form.province.trim() || undefined,
      max_distance: form.max_distance,
      limit: form.limit,
    };
    // กดค้นหาซ้ำด้วยเงื่อนไขเดิม = ดึงข้อมูลใหม่ (ไม่ใช้ผลใน cache)
    if (JSON.stringify(next) === JSON.stringify(query)) void result.refetch();
    else setQuery(next);
  };

  return (
    <>
      <h1>ค้นหาป้ายทะเบียน</h1>
      <form className="card filters" onSubmit={onSubmit} aria-describedby={formError ? "plate-form-error" : undefined}>
        <div className="field field--wide">
          <label htmlFor="plate-q">เลขป้าย</label>
          <input
            id="plate-q"
            type="search"
            value={form.q}
            onChange={(e) => setForm({ ...form, q: e.target.value })}
            placeholder="เช่น 1กข 1234 หรือ 1กข-1234"
            maxLength={16}
            required
            autoComplete="off"
            spellCheck={false}
            aria-describedby="plate-q-hint"
          />
          <small id="plate-q-hint" className="hint">
            พิมพ์บางส่วนได้ เว้นวรรคหรือขีดได้ ระบบจะตัดออกให้เอง
          </small>
        </div>
        <TimeRangeFields from={form.from} to={form.to} onChange={(r) => setForm({ ...form, ...r })} />
        <CameraField value={form.camera_id} onChange={(v) => setForm({ ...form, camera_id: v })} />
        <div className="field">
          <label htmlFor="plate-province">จังหวัด</label>
          <input
            id="plate-province"
            type="text"
            value={form.province}
            onChange={(e) => setForm({ ...form, province: e.target.value })}
            placeholder="ทุกจังหวัด"
            autoComplete="off"
          />
        </div>
        <div className="field">
          <label htmlFor="plate-distance">ยอมให้ป้ายต่างได้ (ตัวอักษร)</label>
          <select
            id="plate-distance"
            value={form.max_distance}
            onChange={(e) => setForm({ ...form, max_distance: Number(e.target.value) })}
            aria-describedby="plate-distance-hint"
          >
            {[0, 1, 2, 3].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          <small id="plate-distance-hint" className="hint">
            {DISTANCE_HELP[form.max_distance]}
          </small>
        </div>
        <LimitField value={form.limit} onChange={(v) => setForm({ ...form, limit: v })} />
        <div className="filters__actions">
          <button type="submit" className="btn btn--primary" disabled={result.isFetching}>
            {result.isFetching ? "กำลังค้นหา…" : "ค้นหา"}
          </button>
        </div>
        {formError ? (
          <div id="plate-form-error" className="alert alert--error filters__error" role="alert">
            {formError}
          </div>
        ) : null}
      </form>

      <BadgeLegend kinds={MATCH_LEGEND} title="ความหมายของป้ายผลการค้น" />

      <ErrorMessage error={result.error} />
      {result.data && query ? <PlateResults rows={result.data} limit={query.limit ?? 100} /> : null}
    </>
  );
}

function PlateResults({ rows, limit }: { rows: PlateMatch[]; limit: number }) {
  const cameraName = useCameraName();
  return (
    <section aria-labelledby="plate-results-title">
      <h2 id="plate-results-title" className="visually-hidden">
        ผลการค้นหา
      </h2>
      <ResultCount count={rows.length} limit={limit} />
      {rows.length === 0 ? (
        <p className="empty">ไม่พบป้ายที่ตรงหรือใกล้เคียงในช่วงเวลานี้ ลองขยายช่วงเวลาหรือเพิ่มระยะต่างของป้าย</p>
      ) : (
        <div className="table-wrap" tabIndex={0} role="region" aria-label="ตารางผลการค้นหา (เลื่อนซ้ายขวาได้)">
          <table>
            <thead>
              <tr>
                <th scope="col">ป้าย</th>
                <th scope="col">การจับคู่</th>
                <th scope="col">กล้อง</th>
                <th scope="col">เวลา</th>
                <th scope="col">ความมั่นใจ OCR</th>
                <th scope="col">เส้นทาง</th>
                <th scope="col">ภาพ</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.sighting_id}>
                  <td>
                    <PlateText text={r.plate_text} province={r.province} />
                  </td>
                  <td>
                    <ConfidenceBadge kind={r.match} />
                    {r.match === "similar" && r.distance > 0 ? (
                      <div className="sub">{describeDistance(r.distance)}</div>
                    ) : null}
                  </td>
                  <td>{cameraName(r.camera_id)}</td>
                  <td className="nowrap">{formatDateTime(r.observed_at)}</td>
                  <td className="num">{formatPercent(r.plate_confidence) ?? "-"}</td>
                  <td>
                    {r.journey_id !== null ? (
                      <Link to={`/journey/${r.journey_id}`}>ดูเส้นทาง #{r.journey_id}</Link>
                    ) : (
                      <span className="muted">ยังไม่ต่อ</span>
                    )}
                  </td>
                  <td>
                    <SightingImage url={r.crop_url} alt={`ภาพรถป้าย ${r.plate_text ?? "อ่านไม่ได้"}`} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
