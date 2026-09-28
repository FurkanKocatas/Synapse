import { afterEach, describe, expect, it, vi } from "vitest";

import { applyAccountLocale } from "./session";
import type { Session } from "./authApi";

const runtime = vi.hoisted(() => ({ current: "tr", setLocale: vi.fn() }));

vi.mock("@/paraglide/runtime.js", () => ({
  getLocale: () => runtime.current,
  isLocale: (value: string) => value === "tr" || value === "en",
  setLocale: runtime.setLocale,
}));

afterEach(() => {
  runtime.setLocale.mockReset();
});

function full(locale: string): Session {
  return {
    auth_level: "full",
    csrf_token: "c",
    user: { id: "u", email: "a@example.org", display_name: "A", role: "member", locale },
  };
}

describe("applyAccountLocale", () => {
  it("switches to the account's language", async () => {
    await applyAccountLocale(full("en"));
    expect(runtime.setLocale).toHaveBeenCalledWith("en");
  });

  it("leaves the interface alone when nothing needs to change", async () => {
    await applyAccountLocale(full("tr"));
    await applyAccountLocale(full("de"));
    await applyAccountLocale({ auth_level: "enroll_mfa", csrf_token: "c", user: null });
    await applyAccountLocale(null);
    expect(runtime.setLocale).not.toHaveBeenCalled();
  });
});
