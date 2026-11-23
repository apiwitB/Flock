import { describe, expect, it } from "vitest";
import { dateToLocalInput, defaultRange, formatDateTime, formatDuration, localInputToIso, validateWindow } from "./time";

describe("localInputToIso", () => {
  it("treats datetime-local input as Bangkok time with +07:00", () => {
    expect(localInputToIso("2026-11-23T08:00")).toBe("2026-11-23T08:00:00+07:00");
  });

  it("keeps seconds and drops fractions", () => {
    expect(localInputToIso("2026-11-23T08:00:45")).toBe("2026-11-23T08:00:45+07:00");
    expect(localInputToIso("2026-11-23T08:00:45.123")).toBe("2026-11-23T08:00:45+07:00");
  });

  it("represents the correct instant", () => {
    expect(new Date(localInputToIso("2026-11-23T06:30")!).toISOString()).toBe("2026-11-22T23:30:00.000Z");
  });

  it("rejects malformed or impossible values", () => {
    for (const bad of ["", "2026-11-23", "2026-11-23 08:00", "2026-13-01T00:00", "2026-02-30T00:00", "2026-11-23T24:00", "abc"]) {
      expect(localInputToIso(bad), bad).toBeNull();
    }
  });
});

describe("dateToLocalInput / defaultRange", () => {
  it("formats a Date as Bangkok local input regardless of machine timezone", () => {
    expect(dateToLocalInput(new Date("2026-11-22T23:30:00Z"))).toBe("2026-11-23T06:30");
  });

  it("round-trips with localInputToIso", () => {
    const d = new Date("2026-01-01T17:05:00Z");
    expect(Date.parse(localInputToIso(dateToLocalInput(d))!)).toBe(d.getTime());
  });

  it("default range is the last 24 hours, end rounded up to the minute", () => {
    const r = defaultRange(new Date("2026-11-23T01:00:30Z"));
    expect(r).toEqual({ from: "2026-11-22T08:01", to: "2026-11-23T08:01" });
    expect(validateWindow(r.from, r.to).ok).toBe(true);
  });
});

describe("validateWindow", () => {
  it("accepts a valid window and returns ISO with offset", () => {
    expect(validateWindow("2026-11-22T08:00", "2026-11-23T08:00")).toEqual({
      ok: true,
      from: "2026-11-22T08:00:00+07:00",
      to: "2026-11-23T08:00:00+07:00",
    });
  });

  it("requires both ends", () => {
    expect(validateWindow("", "2026-11-23T08:00")).toMatchObject({ ok: false });
    expect(validateWindow("2026-11-23T08:00", "")).toMatchObject({ ok: false });
  });

  it("rejects from >= to", () => {
    expect(validateWindow("2026-11-23T08:00", "2026-11-23T08:00")).toEqual({ ok: false, error: "เวลาเริ่มต้องอยู่ก่อนเวลาสิ้นสุด" });
    expect(validateWindow("2026-11-23T09:00", "2026-11-23T08:00")).toMatchObject({ ok: false });
  });

  it("allows exactly 31 days but not more", () => {
    expect(validateWindow("2026-10-01T00:00", "2026-11-01T00:00").ok).toBe(true);
    expect(validateWindow("2026-10-01T00:00", "2026-11-01T00:01")).toEqual({ ok: false, error: "ช่วงเวลากว้างได้ไม่เกิน 31 วัน" });
  });

  it("reports malformed input", () => {
    expect(validateWindow("nope", "2026-11-23T08:00")).toEqual({ ok: false, error: "รูปแบบเวลาเริ่มไม่ถูกต้อง" });
  });
});

describe("display helpers", () => {
  it("formats in Asia/Bangkok", () => {
    // 23:30Z = 06:30 วันถัดไปในเวลาไทย
    const s = formatDateTime("2026-11-22T23:30:00Z");
    expect(s).toContain("06:30:00");
    expect(s).toContain("23");
  });

  it("formats durations in Thai", () => {
    expect(formatDuration(45_000)).toBe("45 วินาที");
    expect(formatDuration(0)).toBe("0 วินาที");
    expect(formatDuration(65 * 60_000)).toBe("1 ชม. 5 นาที");
    expect(formatDuration(26 * 3600_000)).toBe("1 วัน 2 ชม.");
    expect(formatDuration(-1)).toBe("-");
  });
});
