import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, refreshSession, setAccessToken, setSessionLostHandler } from "../lib/api";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("api client", () => {
  beforeEach(() => {
    setAccessToken("expired");
    setSessionLostHandler(() => {});
  });

  it("attaches the bearer token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(200, { ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await api.get("/thing");
    expect(new Headers(fetchMock.mock.calls[0][1].headers).get("Authorization")).toBe("Bearer expired");
  });

  it("refreshes once on a 401 and retries the request", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(401, { detail: "expired" }))
      .mockResolvedValueOnce(json(200, { access_token: "fresh" }))
      .mockResolvedValueOnce(json(200, { value: 42 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(api.get("/thing")).resolves.toEqual({ value: 42 });
    expect(new Headers(fetchMock.mock.calls[2][1].headers).get("Authorization")).toBe("Bearer fresh");
  });

  it("shares one refresh between concurrent callers", async () => {
    let refreshes = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.endsWith("/auth/refresh")) {
          refreshes += 1;
          return json(200, { access_token: "fresh" });
        }
        return json(200, {});
      }),
    );
    await Promise.all([refreshSession(), refreshSession(), refreshSession()]);
    expect(refreshes).toBe(1);
  });

  it("signals a lost session when the refresh fails", async () => {
    const lost = vi.fn();
    setSessionLostHandler(lost);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(401, { detail: "nope" })));
    await expect(api.get("/thing")).rejects.toBeInstanceOf(ApiError);
    expect(lost).toHaveBeenCalledOnce();
  });

  it("surfaces validation messages", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(422, { detail: [{ msg: "Field required" }] })));
    await expect(api.get("/thing")).rejects.toThrow("Field required");
  });
});
