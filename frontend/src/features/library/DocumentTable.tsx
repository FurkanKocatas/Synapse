import {
  CheckCircleIcon,
  CircleNotchIcon,
  DownloadSimpleIcon,
  FilesIcon,
  MagnifyingGlassIcon,
  TrashIcon,
  WarningCircleIcon,
  type Icon,
} from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { motion } from "motion/react";
import { useState, type CSSProperties } from "react";

import { FormError } from "@/components/AuthLayout";
import { CountUp } from "@/components/reactbits/CountUp";
import { Button, buttonVariants } from "@/components/ui/button";
import { IconButton } from "@/components/ui/IconButton";
import { FileIcon } from "@/lib/fileKind";
import { useAction } from "@/lib/useAction";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";
import { getLocale } from "@/paraglide/runtime.js";

import { failureText, formatSize, statusLabel } from "./labels";
import {
  IN_PROGRESS,
  libraryApi,
  type LibraryCollection,
  type LibraryDocument,
} from "./libraryApi";

const REFRESH_MS = 3000;

type Shown = "all" | "ready" | "working" | "failed";

const FILTERS: [Shown, () => string, string, Icon][] = [
  ["all", m.library_filter_all, "text-muted-foreground", FilesIcon],
  ["ready", m.library_filter_ready, "text-success", CheckCircleIcon],
  ["working", m.library_filter_working, "text-warning", CircleNotchIcon],
  ["failed", m.library_filter_failed, "text-destructive", WarningCircleIcon],
];

function groupOf(status: LibraryDocument["status"]): Exclude<Shown, "all"> {
  if (status === "failed") return "failed";
  return IN_PROGRESS.has(status) ? "working" : "ready";
}

// A dot per status: ready green, in progress amber (pulsing), failed red, and text extracted
// (searchable by its words, its meaning still to come) in the action colour.
const DOT: Record<LibraryDocument["status"], string> = {
  queued: "bg-warning animate-pulse",
  parsing: "bg-warning animate-pulse",
  ocr: "bg-warning animate-pulse",
  embedding: "bg-warning animate-pulse",
  parsed: "bg-primary",
  ready: "bg-success",
  failed: "bg-destructive",
};

// By the width of the list itself (container queries), not the window: beside the
// navigation and the collections the list can be narrow on a wide screen.
const COLUMNS =
  "grid grid-cols-[minmax(0,1fr)_auto] @2xl:grid-cols-[minmax(0,1fr)_9rem_5.5rem_10rem_4.5rem]";

export function DocumentTable({ collection }: { collection: LibraryCollection }) {
  const key = ["library", "documents", collection.id];
  const documents = useQuery({
    queryKey: key,
    queryFn: () => libraryApi.documents(collection.id),
    // Keep asking while something is being processed, then stop.
    refetchInterval: (query) =>
      query.state.data?.some((document) => IN_PROGRESS.has(document.status)) ? REFRESH_MS : false,
  });
  const { run, error, busy } = useAction();
  const [confirming, setConfirming] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [shown, setShown] = useState<Shown>("all");
  const locale = getLocale();
  const dates = new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" });

  if (documents.data === undefined) {
    return <p className="text-sm text-muted-foreground">{m.common_loading()}</p>;
  }
  if (documents.data.length === 0) {
    return <p className="text-sm text-muted-foreground">{m.library_empty()}</p>;
  }

  const wanted = filter.trim().toLocaleLowerCase(locale);
  const rows = documents.data.filter(
    (document) =>
      (shown === "all" || groupOf(document.status) === shown) &&
      (wanted === "" || document.title.toLocaleLowerCase(locale).includes(wanted)),
  );

  const counts: Record<Shown, number> = {
    all: documents.data.length,
    ready: 0,
    working: 0,
    failed: 0,
  };
  for (const document of documents.data) counts[groupOf(document.status)] += 1;

  function remove(document: LibraryDocument) {
    setConfirming(null);
    void run(() => libraryApi.remove(document.id), [key]);
  }

  return (
    <div className="@container flex flex-col gap-3">
      {/* How many documents are in each state; each card also filters the list to its state. */}
      <div
        role="group"
        aria-label={m.library_filter_label()}
        className="grid grid-cols-2 gap-2.5 @xl:grid-cols-4"
      >
        {FILTERS.map(([value, label, tone, IconFor], index) => (
          <button
            key={value}
            type="button"
            aria-label={label()}
            aria-pressed={shown === value}
            onClick={() => {
              setShown(value);
            }}
            style={{ "--i": index } as CSSProperties}
            className="lift relative flex animate-rise flex-col items-start gap-1 rounded-xl border bg-card px-3.5 py-3 text-left shadow-raised outline-none focus-visible:ring-2 focus-visible:ring-ring aria-pressed:border-primary"
          >
            {shown === value && (
              <motion.span
                layoutId="library-filter"
                aria-hidden="true"
                className="absolute inset-0 rounded-xl ring-2 ring-primary/25"
                transition={{ type: "spring", bounce: 0, duration: 0.3 }}
              />
            )}
            <span className="flex items-center gap-1.5 text-xs text-subtle-foreground">
              <IconFor weight="fill" className={cn("size-3.5", tone)} aria-hidden="true" />
              {label()}
            </span>
            <span className="text-2xl leading-tight font-semibold tracking-tight">
              <CountUp to={counts[value]} />
            </span>
          </button>
        ))}
      </div>
      <label className="flex h-10 items-center gap-2.5 rounded-xl border border-input bg-card px-3.5 text-muted-foreground transition-[border-color,box-shadow] focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/20">
        <MagnifyingGlassIcon className="size-[18px] shrink-0" aria-hidden="true" />
        <input
          type="search"
          aria-label={m.library_search()}
          placeholder={m.library_search()}
          value={filter}
          onChange={(event) => {
            setFilter(event.target.value);
          }}
          className="min-w-0 flex-1 bg-transparent text-[15px] text-foreground outline-none placeholder:text-muted-foreground"
        />
        <span className="shrink-0 text-xs">
          {m.library_count({ count: String(documents.data.length) })}
        </span>
      </label>
      <FormError message={error} />
      <div className="overflow-hidden rounded-2xl border bg-card shadow-raised">
        <div
          className={cn(
            COLUMNS,
            "hidden h-9 items-center gap-3 border-b bg-sidebar px-4 text-xs text-muted-foreground @2xl:grid",
          )}
        >
          <span>{m.library_col_name()}</span>
          <span>{m.library_col_status()}</span>
          <span>{m.library_col_size()}</span>
          <span>{m.library_col_updated()}</span>
          <span className="sr-only">{m.admin_field_actions()}</span>
        </div>
        {rows.length === 0 && (
          <p className="px-4 py-6 text-sm text-muted-foreground">{m.library_no_match()}</p>
        )}
        <ul className="divide-y">
          {rows.map((document, index) => (
            <li
              key={document.id}
              style={{ "--i": index } as CSSProperties}
              className={cn(
                COLUMNS,
                "min-h-13 animate-rise items-center gap-x-3 px-4 py-2 transition-colors hover:bg-background",
              )}
            >
              <div className="flex min-w-0 items-center gap-3">
                <FileIcon mediaType={document.media_type} name={document.title} />
                <div className="min-w-0">
                  <p className="truncate text-[14.5px] font-medium" title={document.title}>
                    {document.title}
                  </p>
                  {document.status === "failed" && (
                    <p className="truncate text-xs text-destructive">
                      {failureText(document.failure)}
                    </p>
                  )}
                  <p className="flex items-center gap-1.5 text-xs text-muted-foreground @2xl:hidden">
                    <span
                      aria-hidden="true"
                      className={cn("size-1.5 shrink-0 rounded-full", DOT[document.status])}
                    />
                    {statusLabel[document.status]()} · {formatSize(document.size_bytes, locale)}
                  </p>
                </div>
              </div>
              <span
                className={cn(
                  "hidden items-center gap-2 text-[13px] text-subtle-foreground @2xl:flex",
                  document.status === "failed" && "text-destructive",
                )}
              >
                <span
                  aria-hidden="true"
                  className={cn("size-1.5 rounded-full", DOT[document.status])}
                />
                {statusLabel[document.status]()}
              </span>
              <span className="hidden font-mono text-xs text-subtle-foreground @2xl:block">
                {formatSize(document.size_bytes, locale)}
              </span>
              <span className="hidden text-xs text-subtle-foreground @2xl:block">
                {dates.format(new Date(document.updated_at))}
              </span>
              <div className="flex shrink-0 items-center justify-end gap-0.5">
                <a
                  className={buttonVariants({ variant: "ghost", size: "icon-sm" })}
                  href={libraryApi.fileUrl(document.id, document.latest_version)}
                  aria-label={`${m.library_download()}: ${document.title}`}
                  title={m.library_download()}
                >
                  <DownloadSimpleIcon className="size-4" aria-hidden="true" />
                </a>
                {collection.can_write &&
                  (confirming === document.id ? (
                    <Button
                      variant="destructive"
                      size="sm"
                      disabled={busy}
                      onClick={() => {
                        remove(document);
                      }}
                    >
                      {m.library_delete_confirm()}
                    </Button>
                  ) : (
                    <IconButton
                      className="size-7 hover:text-destructive"
                      disabled={busy}
                      label={`${m.library_delete()}: ${document.title}`}
                      onClick={() => {
                        setConfirming(document.id);
                      }}
                    >
                      <TrashIcon aria-hidden="true" />
                    </IconButton>
                  ))}
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
