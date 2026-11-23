import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { errorText } from "./ErrorMessage";

interface Props {
  url: string;
  alt: string;
  /** ข้อความบนปุ่มเมื่อยังไม่โหลด */
  buttonLabel?: string;
  /** โหลดทันที (ใช้เฉพาะหน้าเส้นทาง ซึ่งเป็นการสอบสวนโดยเจตนา) */
  autoLoad?: boolean;
  className?: string;
}

type State = { kind: "idle" } | { kind: "loading" } | { kind: "loaded"; src: string } | { kind: "error"; message: string };

/**
 * ภาพของ sighting โหลดเมื่อผู้ใช้กดเท่านั้น (เว้นแต่ autoLoad)
 * ทุกครั้งที่โหลดภาพถูกบันทึกใน audit log ฝั่งเซิร์ฟเวอร์
 */
export function SightingImage({ url, alt, buttonLabel = "ดูภาพ", autoLoad = false, className }: Props) {
  const [state, setState] = useState<State>({ kind: "idle" });
  const [requested, setRequested] = useState(autoLoad);
  const [attempt, setAttempt] = useState(0);
  const srcRef = useRef<string | null>(null);

  useEffect(() => {
    if (!requested) return;
    const ctrl = new AbortController();
    setState({ kind: "loading" });
    api
      .image(url, ctrl.signal)
      .then((blob) => {
        const src = URL.createObjectURL(blob);
        srcRef.current = src;
        setState({ kind: "loaded", src });
      })
      .catch((e: unknown) => {
        if (ctrl.signal.aborted) return;
        setState({ kind: "error", message: errorText(e) });
      });
    return () => {
      ctrl.abort();
      if (srcRef.current) {
        URL.revokeObjectURL(srcRef.current);
        srcRef.current = null;
      }
    };
  }, [requested, url, attempt]);

  if (!requested) {
    return (
      <button type="button" className="btn btn--small" onClick={() => setRequested(true)}>
        {buttonLabel}
      </button>
    );
  }
  if (state.kind === "loaded") {
    return (
      <a href={state.src} target="_blank" rel="noopener" className={`sighting-image ${className ?? ""}`} title="เปิดภาพขนาดเต็มในแท็บใหม่">
        <img src={state.src} alt={alt} />
      </a>
    );
  }
  if (state.kind === "error") {
    return (
      <span className="image-error" role="status">
        โหลดภาพไม่ได้: {state.message}{" "}
        <button
          type="button"
          className="btn btn--small btn--ghost"
          onClick={() => setAttempt((n) => n + 1)}
        >
          ลองใหม่
        </button>
      </span>
    );
  }
  return (
    <span className="image-loading" role="status">
      กำลังโหลดภาพ…
    </span>
  );
}
