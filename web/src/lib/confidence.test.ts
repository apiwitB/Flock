import { describe, expect, it } from "vitest";
import { badgeAccessibleText, badgeFor, describeDistance, formatPercent, isUncertainLink, LINK_LEGEND, MATCH_LEGEND } from "./confidence";

describe("badgeFor", () => {
  it("maps each state to its Thai label and tone", () => {
    expect(badgeFor("exact")).toMatchObject({ label: "ชัด", tone: "exact" });
    expect(badgeFor("similar")).toMatchObject({ label: "ป้ายคล้าย", tone: "similar" });
    expect(badgeFor("similar_plate")).toMatchObject({ label: "ป้ายคล้าย", tone: "similar" });
    expect(badgeFor("guess")).toMatchObject({ label: "เดา", tone: "guess" });
    expect(badgeFor("partial")).toMatchObject({ label: "ตรงบางส่วน", tone: "partial" });
    expect(badgeFor("new")).toMatchObject({ label: "จุดเริ่ม", tone: "start" });
  });

  it("never styles a guess, similar or partial like an exact match", () => {
    const exact = badgeFor("exact", 1);
    for (const k of ["guess", "similar", "similar_plate", "partial", "new", null, "something-else"]) {
      const b = badgeFor(k, 1);
      expect(b.tone, String(k)).not.toBe(exact.tone);
      expect(b.symbol, String(k)).not.toBe(exact.symbol);
      expect(b.label, String(k)).not.toBe(exact.label);
    }
  });

  it("always shows the score when present", () => {
    expect(badgeFor("guess", 0.873).scoreText).toBe("ลักษณะคล้าย 87%");
    // แม้ embedding เหมือนกันทุกมิติ ก็ยังต้องอ่านว่าเป็นความคล้าย ไม่ใช่ "เดา 100%"
    expect(badgeFor("guess", 1).scoreText).toBe("ลักษณะคล้าย 100%");
    expect(badgeFor("similar_plate", 0.6667).scoreText).toBe("66%");
    expect(badgeFor("exact", 1).scoreText).toBe("100%");
    expect(badgeFor("guess", null).scoreText).toBeNull();
    expect(badgeFor("guess").scoreText).toBeNull();
  });

  it("does not show a score for the start of a journey", () => {
    expect(badgeFor("new", 0.5).scoreText).toBeNull();
  });

  it("falls back to a neutral unknown badge", () => {
    expect(badgeFor(null)).toMatchObject({ label: "ไม่ทราบ", tone: "unknown", scoreText: null });
    expect(badgeFor("toString")).toMatchObject({ tone: "unknown" });
  });

  it("builds accessible text with label, score and description", () => {
    const text = badgeAccessibleText(badgeFor("guess", 0.62));
    expect(text.startsWith("เดา ลักษณะคล้าย 62%:")).toBe(true);
  });

  it("legends only contain known states", () => {
    for (const k of [...MATCH_LEGEND, ...LINK_LEGEND]) expect(badgeFor(k).tone).not.toBe("unknown");
  });
});

describe("formatPercent", () => {
  it("rounds down so nothing looks more certain than it is", () => {
    expect(formatPercent(0.996)).toBe("99%");
    expect(formatPercent(0)).toBe("0%");
  });
  it("clamps and ignores invalid values", () => {
    expect(formatPercent(1.5)).toBe("100%");
    expect(formatPercent(-0.2)).toBe("0%");
    expect(formatPercent(Number.NaN)).toBeNull();
    expect(formatPercent(undefined)).toBeNull();
  });
});

describe("isUncertainLink", () => {
  it("warns for guess and similar_plate only", () => {
    expect(isUncertainLink("guess")).toBe(true);
    expect(isUncertainLink("similar_plate")).toBe(true);
    expect(isUncertainLink("exact")).toBe(false);
    expect(isUncertainLink(null)).toBe(false);
  });
});

describe("describeDistance", () => {
  it("explains fractional distances from look-alike characters", () => {
    expect(describeDistance(0)).toBe("ตรงทุกตัว");
    expect(describeDistance(0.4)).toContain("หน้าตาคล้ายกัน");
    expect(describeDistance(0.8)).toContain("หน้าตาคล้ายกัน");
    expect(describeDistance(1)).toBe("ต่าง 1 ตัว");
    expect(describeDistance(1.4)).toBe("ต่าง 1 ตัว + ตัวที่หน้าตาคล้ายกัน");
  });
});
