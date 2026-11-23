import { badgeAccessibleText, badgeFor, type ConfidenceKind } from "../lib/confidence";

interface Props {
  kind: string | null | undefined;
  score?: number | null | undefined;
}

/** ป้ายระดับความมั่นใจ: สี + สัญลักษณ์ + ข้อความ + คะแนน (ไม่พึ่งสีอย่างเดียว) */
export function ConfidenceBadge({ kind, score }: Props) {
  const info = badgeFor(kind, score);
  const text = badgeAccessibleText(info);
  return (
    <span className={`badge badge--${info.tone}`} title={info.description}>
      <span aria-hidden="true" className="badge__symbol">
        {info.symbol}
      </span>
      <span aria-hidden="true">
        {info.label}
        {info.scoreText ? <span className="badge__score"> {info.scoreText}</span> : null}
      </span>
      <span className="visually-hidden">{text}</span>
    </span>
  );
}

/** คำอธิบายป้ายทั้งหมดในชุด */
export function BadgeLegend({ kinds, title }: { kinds: ConfidenceKind[]; title: string }) {
  return (
    <details className="legend">
      <summary>{title}</summary>
      <dl>
        {kinds.map((k) => {
          const info = badgeFor(k);
          return (
            <div key={k} className="legend__row">
              <dt>
                <ConfidenceBadge kind={k} />
              </dt>
              <dd>{info.description}</dd>
            </div>
          );
        })}
      </dl>
    </details>
  );
}
