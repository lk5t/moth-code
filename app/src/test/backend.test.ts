import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, fetchBackendInfo, isTauri } from "@/lib/backend";

describe("backend client (browser mode)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("is not in Tauri during tests", () => {
    expect(isTauri()).toBe(false);
  });

  it("reports an unreachable backend as starting, not ready", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")));
    const info = await fetchBackendInfo();
    expect(info.status).toBe("starting");
    expect(info.error).toContain("not reachable");
  });

  it("sends JSON and surfaces API error details", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "ok" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 1 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "No MOTH model is loaded" }), { status: 409 }));
    vi.stubGlobal("fetch", fetchMock);
    expect((await fetchBackendInfo()).status).toBe("ready");
    expect(await api("/api/x", { method: "POST", json: { a: 1 } })).toEqual({ id: 1 });
    const [, init] = fetchMock.mock.calls[1];
    expect(init.body).toBe('{"a":1}');
    expect(init.headers["Content-Type"]).toBe("application/json");
    await expect(api("/api/chat")).rejects.toEqual(new ApiError(409, "No MOTH model is loaded"));
  });
});
