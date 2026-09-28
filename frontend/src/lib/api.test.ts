import { afterEach, describe, expect, it, vi } from "vitest";

import { fakeApi } from "@/test/fakeApi";

import { ApiError, apiRequest, NetworkError, rememberCsrfToken } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
  rememberCsrfToken(null);
});

describe("apiRequest", () => {
  it("always identifies the client and sends the CSRF token only on writes", async () => {
    const calls = fakeApi(() => ({ status: 200, body: {} }));
    rememberCsrfToken("token-1");
    await apiRequest("GET", "/api/x");
    await apiRequest("POST", "/api/x", { a: 1 });
    expect(calls[0]?.headers).toEqual({ "X-Synapse-Client": "web" });
    expect(calls[1]?.headers).toMatchObject({
      "X-Synapse-Client": "web",
      "X-Synapse-CSRF": "token-1",
      "Content-Type": "application/json",
    });
    expect(calls[1]?.body).toEqual({ a: 1 });
  });

  it("turns error responses into ApiError with the stable code", async () => {
    fakeApi(() => ({
      status: 429,
      body: { error: "too_many_attempts" },
      headers: { "Retry-After": "8" },
    }));
    const failure = await apiRequest("POST", "/api/x").catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({ status: 429, code: "too_many_attempts", retryAfterSeconds: 8 });
  });

  it("reports non-JSON errors as unexpected", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response("<html>", { status: 502 }))),
    );
    await expect(apiRequest("GET", "/api/x")).rejects.toMatchObject({ code: "unexpected" });
  });

  it("reports unreachable servers as NetworkError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("offline"))),
    );
    await expect(apiRequest("GET", "/api/x")).rejects.toBeInstanceOf(NetworkError);
  });
});
