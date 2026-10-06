// The cards of the system page (SystemPage.tsx), each reading its part of the figures.

import {
  ArrowCounterClockwiseIcon,
  ArrowRightIcon,
  ChartPieSliceIcon,
  FilesIcon,
  HardDrivesIcon,
  PuzzlePieceIcon,
  ScanIcon,
  SealCheckIcon,
  type Icon,
} from "@phosphor-icons/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";

import { adminApi, type Operations } from "./adminApi";
import {
  count,
  PARTS,
  QUERY_KEY,
  READY,
  reasonOf,
  size,
  sum,
  when,
  WORKING,
  type Tone,
} from "./system";

function Card({
  icon: IconFor,
  title,
  lead,
  wide = false,
  children,
}: {
  icon: Icon;
  title: string;
  lead: string;
  wide?: boolean;
  children: ReactNode;
}) {
  return (
    <section
      className={cn(
        "flex animate-rise flex-col rounded-2xl border bg-card p-5 shadow-raised",
        wide && "lg:col-span-2",
      )}
    >
      <h3 className="flex items-center gap-2 text-[15px] font-semibold">
        <IconFor className="size-4 text-muted-foreground" aria-hidden="true" />
        {title}
      </h3>
      <p className="mt-0.5 mb-3.5 text-sm text-muted-foreground">{lead}</p>
      {children}
    </section>
  );
}

function Pill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        tone === "good" && "bg-success/10 text-success",
        tone === "bad" && "bg-destructive/10 text-destructive",
        tone === "neutral" && "bg-muted text-muted-foreground",
      )}
    >
      <span className="size-1.5 rounded-full bg-current" aria-hidden="true" />
      {children}
    </span>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-t py-2.5 text-sm first:border-t-0 first:pt-0">
      <span className="text-subtle-foreground">{label}</span>
      <span className="flex items-center gap-2 text-right font-medium">{children}</span>
    </div>
  );
}

export function Parts({ operations }: { operations: Operations }) {
  const known = operations.services.filter((service) => service.name in PARTS);
  return (
    <Card icon={PuzzlePieceIcon} title={m.system_parts()} lead={m.system_parts_lead()} wide>
      <ul className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
        {known.map((service) => {
          const part = PARTS[service.name];
          if (part === undefined) return null;
          return (
            <li key={service.name} className="flex flex-col gap-1 rounded-xl border px-3.5 py-3">
              <span className="flex items-center justify-between gap-2 text-sm font-medium">
                {part.label()}
                <Pill tone={service.ok ? "good" : "bad"}>
                  {service.ok
                    ? part.model
                      ? m.system_ready()
                      : m.system_running()
                    : m.system_down()}
                </Pill>
              </span>
              <span className="text-xs text-muted-foreground">{part.does()}</span>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

export function Documents({ operations }: { operations: Operations }) {
  const queryClient = useQueryClient();
  const retry = useMutation({
    mutationFn: adminApi.retryProcessing,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QUERY_KEY }),
  });
  const documents = operations.documents;
  const working = sum(documents, WORKING);
  const failed = documents.failed ?? 0;
  const pages = operations.pages.waiting_for_ocr;
  const stats: [string, number][] = [
    [m.system_documents_ready(), sum(documents, READY)],
    [m.system_documents_working(), working],
    [m.system_documents_failed(), failed],
    [m.system_documents_deleting(), operations.deleted_waiting],
  ];
  return (
    <Card icon={FilesIcon} title={m.system_documents()} lead={m.system_documents_lead()}>
      <dl className="mb-3.5 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {stats.map(([label, value]) => (
          <div
            key={label}
            className="flex flex-col-reverse justify-end rounded-xl bg-muted px-3 py-2.5"
          >
            <dt className="text-xs text-subtle-foreground">{label}</dt>
            <dd className="text-2xl font-semibold tabular-nums">{count(value)}</dd>
          </div>
        ))}
      </dl>
      <Row label={m.system_queue()}>
        {working === 0
          ? m.system_queue_none()
          : pages === 0
            ? m.system_queue_documents({ documents: count(working) })
            : m.system_queue_documents_pages({ documents: count(working), pages: count(pages) })}
      </Row>
      {failed > 0 && (
        <Row label={m.system_failed_documents({ count: count(failed) })}>
          <Link
            to="/library"
            className="inline-flex items-center gap-1 text-secondary-foreground hover:underline"
          >
            {m.system_failed_see()}
            <ArrowRightIcon className="size-3.5" aria-hidden="true" />
          </Link>
        </Row>
      )}
      {operations.retryable > 0 && (
        <Row label={m.system_retryable({ count: count(operations.retryable) })}>
          <Button
            variant="outline"
            disabled={retry.isPending}
            onClick={() => {
              retry.mutate();
            }}
          >
            <ArrowCounterClockwiseIcon aria-hidden="true" />
            {m.system_retry()}
          </Button>
        </Row>
      )}
      {retry.isSuccess && (
        <p role="status" className="mt-2 text-sm text-success">
          {m.system_retried({
            count: count(retry.data.reprocessing + retry.data.embedding),
          })}
        </p>
      )}
      {retry.isError && (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {m.system_retry_failed()}
        </p>
      )}
    </Card>
  );
}

export function ScannedPages({ operations }: { operations: Operations }) {
  const pages = operations.pages;
  return (
    <Card icon={ScanIcon} title={m.system_scanned()} lead={m.system_scanned_lead()}>
      <Row label={m.system_scanned_read()}>{count(pages.read_by_ocr)}</Row>
      <Row label={m.system_scanned_uncertain()}>{count(pages.with_uncertain_identifiers)}</Row>
      <Row label={m.system_scanned_unread()}>{count(pages.not_read)}</Row>
      <p className="mt-2.5 text-xs text-muted-foreground">{m.system_scanned_note()}</p>
    </Card>
  );
}

export function Backups({ operations, now }: { operations: Operations; now: Date }) {
  const { latest, latest_ok } = operations.runs;
  const backup = latest.backup;
  const check = latest.backup_verify;
  return (
    <Card icon={HardDrivesIcon} title={m.system_backups()} lead={m.system_backups_lead()}>
      <Row label={m.system_backup_last()}>
        {backup === undefined ? (
          <Pill tone="neutral">{m.system_backup_none()}</Pill>
        ) : (
          <>
            {when(backup.finished_at, now)}
            <Pill tone={backup.ok ? "good" : "bad"}>
              {backup.ok ? m.system_backup_taken() : m.system_backup_failed()}
            </Pill>
          </>
        )}
      </Row>
      {backup !== undefined && !backup.ok && (
        <Row label={m.system_backup_last_good()}>
          {latest_ok.backup === undefined
            ? m.system_never()
            : when(latest_ok.backup.finished_at, now)}
        </Row>
      )}
      <Row label={m.system_backup_check()}>
        {check === undefined ? (
          <Pill tone="neutral">{m.system_check_none()}</Pill>
        ) : (
          <>
            {when(check.finished_at, now)}
            <Pill tone={check.ok ? "good" : "bad"}>
              {check.ok ? m.system_check_ok() : m.system_check_failed()}
            </Pill>
          </>
        )}
      </Row>
      {backup !== undefined && !backup.ok && (
        <p className="mt-2.5 text-xs text-muted-foreground">
          {m.system_reason({ reason: reasonOf(backup) })}
        </p>
      )}
    </Card>
  );
}

export function Space({ operations }: { operations: Operations }) {
  const { files_bytes: files, database_bytes: database } = operations.storage;
  const { disk_free_bytes: free, disk_total_bytes: total } = operations.storage;
  const other = Math.max(0, total - free - files - database);
  const parts: [string, number, string][] = [
    [m.system_space_files(), files, "bg-primary"],
    [m.system_space_database(), database, "bg-primary/45"],
    [m.system_space_other(), other, "bg-input"],
  ];
  const share = (bytes: number) => `${String(total > 0 ? (bytes / total) * 100 : 0)}%`;
  return (
    <Card icon={ChartPieSliceIcon} title={m.system_space()} lead={m.system_space_lead()}>
      <span aria-hidden="true" className="mb-3 flex h-2.5 overflow-hidden rounded-full bg-muted">
        {parts.map(([label, bytes, colour]) => (
          <span
            key={label}
            className={cn("block h-full", colour)}
            style={{ width: share(bytes) }}
          />
        ))}
      </span>
      <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-subtle-foreground">
        {parts.map(([label, bytes, colour]) => (
          <li key={label} className="flex items-center gap-1.5">
            <span className={cn("size-2.5 rounded-sm", colour)} aria-hidden="true" />
            {label} <span className="tabular-nums">{size(bytes)}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2.5 text-sm">
        {m.system_space_free({ free: size(free), total: size(total) })}
      </p>
    </Card>
  );
}

export function AuditLog({ operations, now }: { operations: Operations; now: Date }) {
  const audit = operations.runs.latest.audit_verify;
  const checked = audit?.details.events_checked;
  return (
    <Card icon={SealCheckIcon} title={m.system_audit()} lead={m.system_audit_lead()} wide>
      <Row label={m.system_audit_last()}>
        {audit === undefined ? (
          <Pill tone="neutral">{m.system_audit_none()}</Pill>
        ) : (
          <>
            {when(audit.finished_at, now)}
            <Pill tone={audit.ok ? "good" : "bad"}>
              {audit.ok ? m.system_audit_ok() : m.system_audit_broken()}
            </Pill>
          </>
        )}
      </Row>
      {typeof checked === "number" && <Row label={m.system_audit_checked()}>{count(checked)}</Row>}
    </Card>
  );
}
