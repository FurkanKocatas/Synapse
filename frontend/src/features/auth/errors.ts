// Turns API failures into a sentence for the user, in the current language.

import { ApiError, NetworkError } from "@/lib/api";
import { m } from "@/paraglide/messages.js";

export function errorMessage(error: unknown): string {
  if (error instanceof NetworkError) return m.error_network();
  if (!(error instanceof ApiError)) return m.error_unexpected();
  switch (error.code) {
    case "invalid_credentials":
      return m.error_invalid_credentials();
    case "too_many_attempts":
      return m.error_too_many_attempts({ seconds: String(error.retryAfterSeconds ?? 60) });
    case "invalid_code":
      return m.error_invalid_code();
    case "not_authenticated":
    case "no_second_factor_pending":
      return m.error_session_expired();
    default:
      return m.error_unexpected();
  }
}
