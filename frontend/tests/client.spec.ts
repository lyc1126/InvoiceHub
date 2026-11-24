import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, request } from "../src/api/client";

function respond(status: number, body: unknown) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("request", () => {
  it("returns the parsed payload on success", async () => {
    vi.stubGlobal("fetch", respond(200, { ok: true, value: 1 }));
    await expect(request("/api/v1/health")).resolves.toEqual({ ok: true, value: 1 });
  });

  it("surfaces HTTPException detail with the status code", async () => {
    vi.stubGlobal("fetch", respond(409, { detail: "选择已过期" }));
    await expect(request("/api/v1/x")).rejects.toMatchObject({ message: "选择已过期", status: 409 });
  });

  it("treats ok:false bodies as failures even with HTTP 200", async () => {
    vi.stubGlobal("fetch", respond(200, { ok: false, message: "当前发布包未内置本地 OCR" }));
    await expect(request("/api/v1/ocr/service-start")).rejects.toBeInstanceOf(ApiError);
  });

  it("sends JSON bodies with a content type", async () => {
    const fetchMock = respond(200, { ok: true });
    vi.stubGlobal("fetch", fetchMock);
    await request("/api/v1/settings", { method: "PUT", body: { watch_dir: "x" } });
    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(init.method).toBe("PUT");
    expect(init.body).toBe('{"watch_dir":"x"}');
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
  });

  it("reports a timeout instead of hanging", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn((_path: string, init: RequestInit) =>
        new Promise((_resolve, reject) => init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")))),
      ),
    );
    const pending = request("/api/v1/slow", { timeoutMs: 50 });
    const assertion = expect(pending).rejects.toMatchObject({ message: "请求超时或已取消", status: 0 });
    await vi.advanceTimersByTimeAsync(60);
    await assertion;
  });
});
