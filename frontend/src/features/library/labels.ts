// Translated names for statuses and failure codes coming from the API.

import { m } from "@/paraglide/messages.js";

import type { VersionStatus } from "./libraryApi";

// In the words of someone who does not know how a document is processed: a scan being read is
// "reading" (with a note that it takes a while), and a document searchable by its words is
// "ready" though its meaning is still to be added.
export const statusLabel: Record<VersionStatus, () => string> = {
  queued: m.status_queued,
  parsing: m.status_parsing,
  ocr: m.status_parsing,
  parsed: m.status_ready,
  embedding: m.status_embedding,
  ready: m.status_ready,
  failed: m.status_failed,
};

const failureLabel: Record<string, () => string> = {
  unreadable: m.failure_unreadable,
  encrypted: m.failure_encrypted,
  too_many_pages: m.failure_too_many_pages,
  sheet_too_large: m.failure_sheet_too_large,
  suspicious_package: m.failure_suspicious_package,
  empty: m.failure_empty,
  internal_error: m.failure_internal_error,
};

export function failureText(code: string | null): string {
  return (code !== null && failureLabel[code]?.()) || m.failure_internal_error();
}

/** "1,2 MB" in Turkish, "1.2 MB" in English. */
export function formatSize(bytes: number, locale: string): string {
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = unit === 0 || value >= 10 ? 0 : 1;
  const number = new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(value);
  return `${number} ${units[unit] ?? "B"}`;
}
