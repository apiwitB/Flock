import { afterEach, describe, expect, it, vi } from "vitest";
import {
  api,
  ApiError,
  buildQuery,
  ForbiddenError,
  NotFoundError,
  request,
  setUnauthorizedHandler,
  UnauthorizedError,
  ValidationError,
  validationMessage,
} from "./client";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockFetch(res: Response | (() => Promise<Response>)) {
  const fn = vi.fn(typeof res === "function" ? res : async () => res);
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  setUnauthorizedHandler(null);
});

describe("request", () => {
  it("returns parsed JSON and sends same-origin credentials to a relative URL", async () => {
    const fetchFn = mockFetch(jsonResponse(200, [{ camera_id: "B1" }]));
    await expect(request("/cameras")).resolves.toEqual([{ camera_id: "B1" }]);
    const [url, init] = fetchFn.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/cameras");
    expect(init.credentials).toBe("same-origin");
  });

  it("refuses absolute or protocol-relative URLs", async () => {
    mockFetch(jsonResponse(200, {}));
    await expect(request("https://example.com/x")).rejects.toBeInstanceOf(ApiError);
    await expect(request("//example.com/x")).rejects.toBeInstanceOf(ApiError);
  });

  it("401 throws UnauthorizedError and emits the redirect signal", async () => {
    mockFetch(jsonResponse(401, { detail: "not signed in" }));
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    await expect(request("/sightings")).rejects.toBeInstanceOf(UnauthorizedError);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("login 401 does not emit the redirect signal", async () => {
    mockFetch(jsonResponse(401, { detail: "invalid username or password" }));
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    await expect(api.login("a", "b")).rejects.toBeInstanceOf(UnauthorizedError);
    expect(handler).not.toHaveBeenCalled();
  });

  it("me() returns null on 401 without signalling", async () => {
    mockFetch(jsonResponse(401, { detail: "not signed in" }));
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    await expect(api.me()).resolves.toBeNull();
    expect(handler).not.toHaveBeenCalled();
  });

  it("403 throws ForbiddenError with a Thai message and does not signal 401", async () => {
    mockFetch(jsonResponse(403, { detail: "requires role investigator" }));
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    const err = await request("/search/plates?q=1").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ForbiddenError);
    expect((err as ForbiddenError).status).toBe(403);
    expect((err as ForbiddenError).message).toBe("บัญชีของคุณไม่มีสิทธิ์ใช้งานส่วนนี้");
    expect((err as ForbiddenError).detail).toBe("requires role investigator");
    expect(handler).not.toHaveBeenCalled();
  });

  it("404 throws NotFoundError", async () => {
    mockFetch(jsonResponse(404, { detail: "journey not found" }));
    await expect(api.journey(9)).rejects.toBeInstanceOf(NotFoundError);
  });

  it("422 throws ValidationError with a Thai message", async () => {
    mockFetch(jsonResponse(422, { detail: "unknown province: xyz" }));
    const err = await request("/search/plates?q=1").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ValidationError);
    expect((err as Error).message).toBe('ไม่รู้จักจังหวัด "xyz"');
  });

  it("other statuses throw ApiError with the status", async () => {
    mockFetch(new Response("oops", { status: 500 }));
    const err = await request("/sightings").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(500);
  });

  it("network failure becomes ApiError status 0", async () => {
    mockFetch(() => Promise.reject(new TypeError("Failed to fetch")));
    const err = await request("/sightings").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(0);
  });

  it("204 resolves to undefined", async () => {
    mockFetch(new Response(null, { status: 204 }));
    await expect(api.logout()).resolves.toBeUndefined();
  });

  it("image() 401 also signals redirect", async () => {
    mockFetch(jsonResponse(401, { detail: "not signed in" }));
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    await expect(api.image("/sightings/x/image/crop")).rejects.toBeInstanceOf(UnauthorizedError);
    expect(handler).toHaveBeenCalledTimes(1);
  });
});

describe("validationMessage", () => {
  it("translates known server messages", () => {
    expect(validationMessage("'from' must be before 'to'")).toBe("เวลาเริ่มต้องอยู่ก่อนเวลาสิ้นสุด");
    expect(validationMessage("time window must be at most 31 days")).toBe("ช่วงเวลากว้างได้ไม่เกิน 31 วัน");
  });
  it("formats pydantic error lists with Thai field names", () => {
    const msg = validationMessage([{ loc: ["query", "max_distance"], msg: "Input should be less than or equal to 3" }]);
    expect(msg).toContain("ระยะต่างของป้าย");
    expect(msg).toContain("less than or equal to 3");
  });
  it("falls back for unknown shapes", () => {
    expect(validationMessage(undefined)).toBe("ข้อมูลไม่ถูกต้อง");
  });
});

describe("buildQuery", () => {
  it("skips empty values and encodes the rest", () => {
    expect(buildQuery({ q: "1กข 1234", from: "2026-11-23T08:00:00+07:00", camera_id: "", province: undefined, max_distance: 2 })).toBe(
      "?q=1%E0%B8%81%E0%B8%82+1234&from=2026-11-23T08%3A00%3A00%2B07%3A00&max_distance=2",
    );
    expect(buildQuery({})).toBe("");
  });
});
