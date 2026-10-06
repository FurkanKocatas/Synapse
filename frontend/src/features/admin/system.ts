// What the system page shows and how: the parts, why a backup failed, what needs attention,
// and dates and sizes as people read them (SystemPage.tsx).

import {
  ArrowCounterClockwiseIcon,
  ChartPieSliceIcon,
  ChatCircleSlashIcon,
  FilesIcon,
  HardDrivesIcon,
  MagnifyingGlassIcon,
  SealWarningIcon,
  WarningIcon,
  type Icon,
} from "@phosphor-icons/react";

import { m } from "@/paraglide/messages.js";
import { getLocale } from "@/paraglide/runtime.js";

import type { Operations, Run } from "./adminApi";

export const QUERY_KEY = ["admin", "operations"];

const DAY_MS = 24 * 60 * 60 * 1000;
// A nightly backup older than this is reported (synapsectl doctor's limit too).
const BACKUP_MAX_DAYS = 2;
// Less free space than this share of the disk is reported.
const LOW_SPACE = 0.1;

export const WORKING = ["queued", "parsing", "ocr", "embedding"];
export const READY = ["ready", "parsed"];

export type Tone = "good" | "bad" | "neutral";

interface Part {
  label: () => string;
  does: () => string;
  // What the users notice while it is not running.
  effect: () => string;
  // A process is "running"; a model is "ready".
  model: boolean;
}

export const PARTS: Record<string, Part> = {
  database: {
    label: m.system_part_database,
    does: m.system_part_database_does,
    effect: m.system_issue_database,
    model: false,
  },
  worker: {
    label: m.system_part_worker,
    does: m.system_part_worker_does,
    effect: m.system_issue_worker,
    model: false,
  },
  scheduler: {
    label: m.system_part_scheduler,
    does: m.system_part_scheduler_does,
    effect: m.system_issue_scheduler,
    model: false,
  },
  embedding: {
    label: m.system_part_embedding,
    does: m.system_part_embedding_does,
    effect: m.system_issue_embedding,
    model: true,
  },
  reranking: {
    label: m.system_part_reranking,
    does: m.system_part_reranking_does,
    effect: m.system_issue_reranking,
    model: true,
  },
  chat: {
    label: m.system_part_chat,
    does: m.system_part_chat_does,
    effect: m.system_issue_chat,
    model: true,
  },
};

// Why a backup or its check failed, from the reason synapsectl gives (backup.py).
const REASONS: Record<string, () => string> = {
  repository_missing: m.system_reason_repository_missing,
  not_configured: m.system_reason_not_configured,
  database_down: m.system_reason_database_down,
  disk_full: m.system_reason_disk_full,
  audit_differs: m.system_reason_audit_differs,
  rows_differ: m.system_reason_rows_differ,
  dump_damaged: m.system_reason_dump_damaged,
};

export interface Issue {
  key: string;
  icon: Icon;
  title: string;
  what: string;
  // Broken rather than late or stopped: the audit log, or nothing works.
  serious: boolean;
}

export function reasonOf(run: Run | undefined): string {
  const reason = run?.details.reason;
  return (typeof reason === "string" ? REASONS[reason] : undefined)?.() ?? m.system_reason_other();
}

export function count(value: number): string {
  return new Intl.NumberFormat(getLocale()).format(value);
}

/** What needs the administrator, most serious first; empty when all is well. */
export function issuesOf(operations: Operations, now: Date): Issue[] {
  const issues: Issue[] = [];
  for (const service of operations.services) {
    const part = PARTS[service.name];
    if (service.ok || part === undefined) continue;
    issues.push({
      key: `part-${service.name}`,
      icon: service.name === "chat" ? ChatCircleSlashIcon : WarningIcon,
      title: m.system_issue_part_down({ part: part.label() }),
      what: part.effect(),
      serious: service.name === "database",
    });
  }

  const { latest, latest_ok } = operations.runs;
  if (latest.audit_verify?.ok === false) {
    issues.push({
      key: "audit",
      icon: SealWarningIcon,
      title: m.system_issue_audit_broken(),
      what: m.system_issue_audit_broken_what(),
      serious: true,
    });
  }
  const backup = latest.backup;
  if (backup === undefined) {
    issues.push({
      key: "backup-never",
      icon: HardDrivesIcon,
      title: m.system_issue_backup_never(),
      what: m.system_issue_backup_never_what(),
      serious: false,
    });
  } else if (!backup.ok) {
    const good = latest_ok.backup;
    issues.push({
      key: "backup-failed",
      icon: HardDrivesIcon,
      title: m.system_issue_backup_failed(),
      what: `${reasonOf(backup)} ${m.system_issue_backup_failed_what({
        when: good === undefined ? m.system_never() : when(good.finished_at, now),
      })}`,
      serious: false,
    });
  } else {
    const days = Math.floor((now.getTime() - new Date(backup.finished_at).getTime()) / DAY_MS);
    if (days > BACKUP_MAX_DAYS) {
      issues.push({
        key: "backup-old",
        icon: HardDrivesIcon,
        title: m.system_issue_backup_old({ days: count(days) }),
        what: m.system_issue_backup_old_what(),
        serious: false,
      });
    }
  }
  if (latest.backup_verify?.ok === false) {
    issues.push({
      key: "backup-check",
      icon: HardDrivesIcon,
      title: m.system_issue_check_failed(),
      what: `${reasonOf(latest.backup_verify)} ${m.system_tell_company()}`,
      serious: false,
    });
  }
  const missing = latest.files_sweep?.details.rows_without_file;
  if (typeof missing === "number" && missing > 0) {
    issues.push({
      key: "files-missing",
      icon: FilesIcon,
      title: m.system_issue_files_missing(),
      what: m.system_issue_files_missing_what(),
      serious: false,
    });
  }
  if (operations.retryable > 0) {
    issues.push({
      key: "retryable",
      icon: ArrowCounterClockwiseIcon,
      title: m.system_issue_retryable({ count: count(operations.retryable) }),
      what: m.system_issue_retryable_what(),
      serious: false,
    });
  }
  const problems = operations.problems;
  if ((problems.ready_without_chunks ?? 0) + (problems.ready_chunks_without_vectors ?? 0) > 0) {
    issues.push({
      key: "search-gaps",
      icon: MagnifyingGlassIcon,
      title: m.system_issue_search_gaps(),
      what: m.system_tell_company(),
      serious: false,
    });
  }
  if ((problems.deleted_not_purged ?? 0) > 0) {
    issues.push({
      key: "purge-late",
      icon: FilesIcon,
      title: m.system_issue_purge_late({ count: count(problems.deleted_not_purged ?? 0) }),
      what: m.system_issue_purge_late_what(),
      serious: false,
    });
  }
  if ((problems.files_no_version_names ?? 0) > 0) {
    issues.push({
      key: "unowned-files",
      icon: FilesIcon,
      title: m.system_issue_unowned_files(),
      what: m.system_issue_unowned_files_what(),
      serious: false,
    });
  }
  const { disk_free_bytes: free, disk_total_bytes: total } = operations.storage;
  if (total > 0 && free / total < LOW_SPACE) {
    issues.push({
      key: "space",
      icon: ChartPieSliceIcon,
      title: m.system_issue_disk_low(),
      what: m.system_issue_disk_low_what({ free: size(free) }),
      serious: false,
    });
  }
  return issues.sort((a, b) => Number(b.serious) - Number(a.serious));
}

/** "Today 02:30", "Yesterday 02:30" or "3 October 02:30". */
export function when(iso: string, now: Date): string {
  const moment = new Date(iso);
  const locale = getLocale();
  const time = new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }).format(
    moment,
  );
  const day = (date: Date) => new Date(date).setHours(0, 0, 0, 0);
  const daysAgo = Math.round((day(now) - day(moment)) / DAY_MS);
  if (daysAgo === 0) return m.system_today({ time });
  if (daysAgo === 1) return m.system_yesterday({ time });
  return new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  }).format(moment);
}

/** Bytes as people read them: "18.4 GB", "350 MB". */
export function size(bytes: number): string {
  const gigabytes = bytes / 1024 ** 3;
  const [value, unit, digits] =
    gigabytes >= 1 ? [gigabytes, "gigabyte", 1] : [bytes / 1024 ** 2, "megabyte", 0];
  return new Intl.NumberFormat(getLocale(), {
    style: "unit",
    unit,
    maximumFractionDigits: digits,
  }).format(value);
}

export function sum(counts: Record<string, number>, keys: string[]): number {
  return keys.reduce((total, key) => total + (counts[key] ?? 0), 0);
}

/** The operations page: whether Synapse's parts run, documents are read and backups are taken,
 * in words anyone can follow; what needs attention first. Administrators only. */
