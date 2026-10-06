// Turns API failures into a sentence for the user, in the current language.

import { ApiError, NetworkError } from "@/lib/api";
import { m } from "@/paraglide/messages.js";

export function errorMessage(error: unknown): string {
  if (error instanceof NetworkError) return m.error_network();
  // The browser's WebAuthn API reports a closed prompt, a timeout and an abort alike. Its
  // errors are DOMExceptions, which are not always instances of Error, so go by the name.
  const name = errorName(error);
  if (name === "NotAllowedError" || name === "AbortError") return m.error_passkey_cancelled();
  if (name === "InvalidStateError") return m.error_passkey_exists();
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
    case "invalid_metadata":
      return m.error_invalid_metadata();
    case "file_too_large":
      return m.error_file_too_large();
    case "unknown_type":
      return m.error_unknown_type();
    case "legacy_office":
      return m.error_legacy_office();
    case "empty_file":
      return m.error_empty_file();
    case "duplicate_document":
      return m.error_duplicate_document();
    case "own_account":
      return m.error_own_account();
    case "passkey_failed":
      return m.error_passkey_failed();
    case "no_passkey":
      return m.error_no_passkey();
    case "last_second_factor":
      return m.error_last_second_factor();
    case "passkeys_unavailable":
      return m.error_passkeys_unavailable();
    case "last_administrator":
      return m.error_last_administrator();
    case "conflict":
      return m.error_conflict();
    case "not_found":
      return m.error_not_found();
    case "forbidden":
      return m.error_forbidden();
    case "classic_chat_disabled":
      return m.error_classic_chat_disabled();
    default:
      return m.error_unexpected();
  }
}

function errorName(error: unknown): string | undefined {
  if (typeof error !== "object" || error === null || !("name" in error)) return undefined;
  return typeof error.name === "string" ? error.name : undefined;
}
