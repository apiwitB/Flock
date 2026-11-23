import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Sighting } from "../api/types";
import { useMe } from "../auth";
import { ConfidenceBadge } from "../components/Badge";
import { ErrorMessage } from "../components/ErrorMessage";
import { CameraField, LimitField, PlateText, ResultCount, TimeRangeFields, useCameraName } from "../components/fields";
import { SightingImage } from "../components/SightingImage";
import { attributeSummary, COLOR_LABELS, VEHICLE_TYPE_LABELS } from "../lib/attributes";
import { formatPercent } from "../lib/confidence";
import { hasRole } from "../lib/roles";
import { formatDateTime, validateWindow } from "../lib/time";
import { useSearchState } from "../searchState";

function SuggestField({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: Record<string, string>;
}) {
  const id = useId();
  const listId = useId();
  const hintId = useId();
  // ค่าที่ซ้ำความหมาย (gray/grey) แสดงครั้งเดียว
  const seen = new Set<string>();
  const entries = Object.entries(options).filter(([, th]) => (seen.has(th) ? false : (seen.add(th), true)));
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="text"
        list={listId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="ทั้งหมด"
        autoComplete="off"
        spellCheck={false}
        aria-describedby={hintId}
      />
      <datalist id={listId}>
        {entries.map(([en, th]) => (
          <option key={en} value={en}>
            {th}
          </option>
        ))}
      </datalist>
      <small id={hintId} className="hint">
        {value && options[value.toLowerCase()] ? `= ${options[value.toLowerCase()]}` : "ค่าภาษาอังกฤษตามที่ระบบบันทึก เช่น " + entries.slice(0, 3).map(([en]) => en).join(", ")}
      </small>
    </div>
  );
}

export function BrowsePage() {
  const { browseForm: form, setBrowseForm: setForm, browseQuery: query, setBrowseQuery: setQuery } = useSearchState();
  const [formError, setFormError] = useState<string | null>(null);

  const result = useQuery({
    queryKey: ["sightings", query],
    queryFn: ({ signal }) => api.sightings(query!, signal),
    enabled: query !== null,
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 30_000,
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const w = validateWindow(form.from, form.to);
    if (!w.ok) return setFormError(w.error);
    setFormError(null);
    const next = {
      from: w.from,
      to: w.to,
      camera_id: form.camera_id.trim() || undefined,
      color: form.color.trim().toLowerCase() || undefined,
      vehicle_type: form.vehicle_type.trim().toLowerCase() || undefined,
      limit: form.limit,
    };
    // กดซ้ำด้วยเงื่อนไขเดิม = ดึงข้อมูลใหม่ (ไม่ใช้ผลใน cache)
    if (JSON.stringify(next) === JSON.stringify(query)) void result.refetch();
    else setQuery(next);
  };

  return (
    <>
      <h1>ดูรายการรถ</h1>
      <form className="card filters" onSubmit={onSubmit}>
        <TimeRangeFields from={form.from} to={form.to} onChange={(r) => setForm({ ...form, ...r })} />
        <CameraField value={form.camera_id} onChange={(v) => setForm({ ...form, camera_id: v })} />
        <SuggestField label="สี" value={form.color} onChange={(v) => setForm({ ...form, color: v })} options={COLOR_LABELS} />
        <SuggestField
          label="ประเภทรถ"
          value={form.vehicle_type}
          onChange={(v) => setForm({ ...form, vehicle_type: v })}
          options={VEHICLE_TYPE_LABELS}
        />
        <LimitField value={form.limit} onChange={(v) => setForm({ ...form, limit: v })} />
        <div className="filters__actions">
          <button type="submit" className="btn btn--primary" disabled={result.isFetching}>
            {result.isFetching ? "กำลังค้นหา…" : "แสดงรายการ"}
          </button>
        </div>
        {formError ? (
          <div className="alert alert--error filters__error" role="alert">
            {formError}
          </div>
        ) : null}
      </form>

      <ErrorMessage error={result.error} />
      {result.data && query ? <BrowseResults rows={result.data} limit={query.limit ?? 100} /> : null}
    </>
  );
}

function BrowseResults({ rows, limit }: { rows: Sighting[]; limit: number }) {
  const cameraName = useCameraName();
  const { data: me } = useMe();
  const investigator = hasRole(me?.role, "investigator");
  return (
    <section aria-labelledby="browse-results-title">
      <h2 id="browse-results-title" className="visually-hidden">
        รายการรถ
      </h2>
      <ResultCount count={rows.length} limit={limit} />
      {rows.length === 0 ? (
        <p className="empty">ไม่พบรถตามเงื่อนไขในช่วงเวลานี้</p>
      ) : (
        <div className="table-wrap" tabIndex={0} role="region" aria-label="ตารางรายการรถ (เลื่อนซ้ายขวาได้)">
          <table>
            <thead>
              <tr>
                <th scope="col">เวลา</th>
                <th scope="col">กล้อง</th>
                <th scope="col">ป้าย</th>
                <th scope="col">ความมั่นใจ OCR</th>
                <th scope="col">สี · ประเภท</th>
                <th scope="col">การต่อเส้นทาง</th>
                {investigator ? <th scope="col">ภาพ</th> : null}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.sighting_id}>
                  <td className="nowrap">{formatDateTime(r.observed_at)}</td>
                  <td>{cameraName(r.camera_id)}</td>
                  <td>
                    <PlateText text={r.plate_text} province={r.province} />
                  </td>
                  <td className="num">{formatPercent(r.plate_confidence) ?? "-"}</td>
                  <td>{attributeSummary(r.attributes)}</td>
                  <td>
                    {r.journey_id !== null ? (
                      <>
                        <ConfidenceBadge kind={r.link_method} score={r.link_score} />
                        <div className="sub">
                          {investigator ? <Link to={`/journey/${r.journey_id}`}>เส้นทาง #{r.journey_id}</Link> : `เส้นทาง #${r.journey_id}`}
                        </div>
                      </>
                    ) : (
                      <span className="muted">ยังไม่ต่อ</span>
                    )}
                  </td>
                  {investigator ? (
                    <td>
                      <SightingImage url={r.crop_url} alt={`ภาพรถที่ ${cameraName(r.camera_id)} เวลา ${formatDateTime(r.observed_at)}`} />
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
