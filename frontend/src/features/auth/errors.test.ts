import { describe, expect, it } from "vitest";

import { ApiError, NetworkError } from "@/lib/api";
import { m } from "@/paraglide/messages.js";

import { errorMessage } from "./errors";

describe("errorMessage", () => {
  it("maps known codes to translated sentences", () => {
    expect(errorMessage(new ApiError(401, "invalid_credentials", null))).toBe(
      m.error_invalid_credentials(),
    );
    expect(errorMessage(new ApiError(429, "too_many_attempts", 12))).toBe(
      m.error_too_many_attempts({ seconds: "12" }),
    );
    expect(errorMessage(new NetworkError(null))).toBe(m.error_network());
  });

  it("explains what the browser's passkey prompt reports", () => {
    const closed = new DOMException(
      "The operation either timed out or was not allowed.",
      "NotAllowedError",
    );
    expect(errorMessage(closed)).toBe(m.error_passkey_cancelled());
    expect(errorMessage(new DOMException("", "InvalidStateError"))).toBe(m.error_passkey_exists());
    expect(errorMessage(new ApiError(400, "passkey_failed", null))).toBe(m.error_passkey_failed());
  });

  it("never shows raw codes for unknown errors", () => {
    expect(errorMessage(new ApiError(500, "something_new", null))).toBe(m.error_unexpected());
    expect(errorMessage(new Error("boom"))).toBe(m.error_unexpected());
  });
});
