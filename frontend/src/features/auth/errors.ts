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
    case "wrong_password":
      return m.error_wrong_password();
    case "email_taken":
      return m.error_email_taken();
    case "password_too_short":
      return m.error_password_too_short();
    case "password_too_long":
      return m.error_password_too_long();
    case "password_contains_context":
      return m.error_password_contains_context();
    case "last_administrator":
      return m.error_last_administrator();
    case "conflict":
      return m.error_conflict();
    case "not_found":
      return m.error_not_found();
    case "forbidden":
      return m.error_forbidden();
    default:
      return m.error_unexpected();
  }
}
