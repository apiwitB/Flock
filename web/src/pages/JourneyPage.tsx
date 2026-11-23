import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Journey, Sighting } from "../api/types";
import { BadgeLegend, ConfidenceBadge } from "../components/Badge";
import { ErrorMessage } from "../components/ErrorMessage";
import { PlateText, useCameraName } from "../components/fields";
import { SightingImage } from "../components/SightingImage";
import { attributeRows } from "../lib/attributes";
import { badgeFor, formatPercent, isUncertainLink, LINK_LEGEND } from "../lib/confidence";
import { formatDateTime, formatDuration } from "../lib/time";

/** React Router เก็บลำดับใน history.state.idx: > 0 แปลว่ามาจากหน้าอื่นในแอป */
function canGoBack(): boolean {
  const idx = (window.history.state as { idx?: unknown } | null)?.idx;
  return typeof idx === "number" && idx > 0;
}

export function JourneyPage() {
  const navigate = useNavigate();
  const { id } = useParams();
  const journeyId = id && /^\d+$/.test(id) ? Number(id) : null;

  const result = useQuery({
    queryKey: ["journey", journeyId],
    queryFn: ({ signal }) => api.journey(journeyId!, signal),
    enabled: journeyId !== null,
    retry: false,
    staleTime: 30_000,
  });

  if (journeyId === null) {
    return (
      <div className="alert alert--error" role="alert">
        หมายเลขเส้นทางไม่ถูกต้อง
      </div>
    );
  }

  return (
    <>
      <p className="back">
        {canGoBack() ? (
          <button type="button" className="btn btn--ghost btn--small" onClick={() => navigate(-1)}>
            ← กลับไปผลการค้นหา
          </button>
        ) : (
          <Link to="/plates">← ไปหน้าค้นหาป้าย</Link>
        )}
      </p>
      {result.isPending ? <p className="loading">กำลังโหลดเส้นทาง…</p> : null}
      <ErrorMessage error={result.error} />
      {result.data ? <JourneyView journey={result.data} /> : null}
    </>
  );
}

function JourneyView({ journey: j }: { journey: Journey }) {
  const duration = Date.parse(j.last_seen) - Date.parse(j.first_seen);
  const uncertain = isUncertainLink(j.weakest_link);
  const weakest = badgeFor(j.weakest_link);
  return (
    <>
      <header className="card journey-header">
        <h1>
          เส้นทางรถ #{j.journey_id}
          <span className={`status ${j.closed ? "status--closed" : "status--open"}`}>{j.closed ? "ปิดแล้ว" : "ยังเปิดอยู่"}</span>
        </h1>
        <dl className="facts">
          <div>
            <dt>ป้าย</dt>
            <dd>
              <PlateText text={j.plate_text} province={j.province} />
              {j.plate_confidence !== null ? <span className="sub"> ความมั่นใจ OCR {formatPercent(j.plate_confidence)}</span> : null}
            </dd>
          </div>
          <div>
            <dt>เห็นครั้งแรก</dt>
            <dd>{formatDateTime(j.first_seen)}</dd>
          </div>
          <div>
            <dt>เห็นครั้งล่าสุด</dt>
            <dd>{formatDateTime(j.last_seen)}</dd>
          </div>
          <div>
            <dt>ระยะเวลา</dt>
            <dd>{formatDuration(duration)}</dd>
          </div>
          <div>
            <dt>จำนวนจุด</dt>
            <dd>{j.sightings.length}</dd>
          </div>
          <div>
            <dt>ช่วงที่มั่นใจน้อยที่สุด</dt>
            <dd>{j.weakest_link ? <ConfidenceBadge kind={j.weakest_link} /> : <span className="muted">-</span>}</dd>
          </div>
        </dl>
        {!j.closed ? <p className="hint">เส้นทางยังเปิดอยู่: รถอาจยังอยู่ในอาคาร หรือระบบยังไม่เห็นรถที่ทางออก</p> : null}
      </header>

      {uncertain ? (
        <div className={`warning-banner warning-banner--${weakest.tone}`} role="alert">
          <strong>
            <span aria-hidden="true">⚠ </span>เส้นทางนี้บางช่วงเป็นการอนุมาน ไม่ใช่ข้อเท็จจริงที่แน่นอน
          </strong>
          <p>
            {j.weakest_link === "guess"
              ? "มีจุดที่ระบบ \"เดา\" ว่าเป็นรถคันเดียวกันจากลักษณะรถ ตำแหน่งกล้อง และเวลา โดยไม่มีป้ายให้เทียบ อาจเป็นรถคนละคัน"
              : "มีจุดที่ต่อด้วย \"ป้ายคล้าย\" (เลขป้ายไม่ตรงทุกตัว) อาจเป็นรถคนละคันที่ป้ายคล้ายกัน"}
            {" "}ตรวจภาพของจุดที่มีป้ายสีส้ม/แดงก่อนนำไปใช้อ้างอิง
          </p>
        </div>
      ) : null}

      <BadgeLegend kinds={LINK_LEGEND} title="ความหมายของป้ายการต่อเส้นทาง" />

      <h2>ไทม์ไลน์</h2>
      {j.sightings.length === 0 ? (
        <p className="empty">ไม่มีจุดในเส้นทางนี้</p>
      ) : (
        <ol className="timeline">
          {j.sightings.map((s, i) => (
            <TimelineStep key={s.sighting_id} s={s} index={i} prev={i > 0 ? j.sightings[i - 1] : undefined} />
          ))}
        </ol>
      )}
    </>
  );
}

function TimelineStep({ s, index, prev }: { s: Sighting; index: number; prev: Sighting | undefined }) {
  const cameraName = useCameraName();
  const info = badgeFor(s.link_method, s.link_score);
  const gap = prev ? Date.parse(s.observed_at) - Date.parse(prev.observed_at) : null;
  const attrs = attributeRows(s.attributes);
  const where = cameraName(s.camera_id);
  return (
    <li className={`timeline__step timeline__step--${info.tone}`}>
      <span className="timeline__dot" aria-hidden="true">
        {index + 1}
      </span>
      <article className="card timeline__card" aria-label={`จุดที่ ${index + 1}: ${where}`}>
        <div className="timeline__head">
          <div>
            <div className="timeline__time">{formatDateTime(s.observed_at)}</div>
            <div className="timeline__camera">{where}</div>
            {gap !== null ? <div className="sub">หลังจุดก่อนหน้า {formatDuration(gap)}</div> : null}
          </div>
          <ConfidenceBadge kind={s.link_method} score={s.link_score} />
        </div>
        <div className="timeline__body">
          <div className="timeline__image">
            <SightingImage url={s.crop_url} alt={`ภาพรถที่ ${where} เวลา ${formatDateTime(s.observed_at)}`} autoLoad />
          </div>
          <dl className="facts facts--compact">
            <div>
              <dt>ป้ายที่อ่านได้</dt>
              <dd>
                <PlateText text={s.plate_text} province={s.province} />
                {s.plate_confidence !== null ? <span className="sub"> ({formatPercent(s.plate_confidence)})</span> : null}
              </dd>
            </div>
            {attrs.map((a) => (
              <div key={a.name}>
                <dt>{a.label}</dt>
                <dd>
                  {a.value}
                  {a.confidence ? <span className="sub"> ({a.confidence})</span> : null}
                </dd>
              </div>
            ))}
          </dl>
        </div>
        <div className="timeline__context">
          <SightingImage
            url={s.context_url}
            alt={`ภาพมุมกว้างจาก ${where} เวลา ${formatDateTime(s.observed_at)}`}
            buttonLabel="ดูภาพมุมกว้าง"
            className="sighting-image--wide"
          />
        </div>
      </article>
    </li>
  );
}
