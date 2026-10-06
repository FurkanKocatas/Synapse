import {
  CheckCircleIcon,
  CircleNotchIcon,
  FilesIcon,
  FolderOpenIcon,
  MagnifyingGlassIcon,
  WarningCircleIcon,
  type Icon,
} from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { motion } from "motion/react";
import { useState, type CSSProperties } from "react";

import { CountUp } from "@/components/reactbits/CountUp";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";
import { getLocale } from "@/paraglide/runtime.js";

import { COLUMNS, DocumentRow } from "./DocumentRow";
import {
  IN_PROGRESS,
  libraryApi,
  type LibraryCollection,
  type LibraryDocument,
} from "./libraryApi";

const REFRESH_MS = 3000;

type Shown = "all" | "ready" | "working" | "failed";

// Each card: what it shows, its name, what that means for the user, its colour and icon.
const FILTERS: [Shown, () => string, () => string, string, Icon][] = [
  ["all", m.library_filter_all, m.library_hint_all, "text-muted-foreground", FilesIcon],
  ["ready", m.library_filter_ready, m.library_hint_ready, "text-success", CheckCircleIcon],
  ["working", m.library_filter_working, m.library_hint_working, "text-warning", CircleNotchIcon],
  ["failed", m.library_filter_failed, m.library_hint_failed, "text-destructive", WarningCircleIcon],
];

function groupOf(status: LibraryDocument["status"]): Exclude<Shown, "all"> {
  if (status === "failed") return "failed";
  return IN_PROGRESS.has(status) ? "working" : "ready";
}

export function DocumentTable({
  collection,
  onOpen,
}: {
  collection: LibraryCollection;
  onOpen: (document: LibraryDocument) => void;
}) {
  const key = ["library", "documents", collection.id];
  const documents = useQuery({
    queryKey: key,
    queryFn: () => libraryApi.documents(collection.id),
    // Keep asking while something is being processed, then stop.
    refetchInterval: (query) =>
      query.state.data?.some((document) => IN_PROGRESS.has(document.status)) ? REFRESH_MS : false,
  });
  const [filter, setFilter] = useState("");
  const [shown, setShown] = useState<Shown>("all");
  const locale = getLocale();

  if (documents.data === undefined) {
    return <p className="text-sm text-muted-foreground">{m.common_loading()}</p>;
  }
  if (documents.data.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed px-6 py-14 text-center">
        <FolderOpenIcon
          weight="duotone"
          className="size-10 text-secondary-foreground"
          aria-hidden="true"
        />
        <p className="font-medium">{m.library_empty()}</p>
        <p className="max-w-sm text-sm text-muted-foreground">
          {collection.can_write ? m.library_empty_add() : m.library_empty_read()}
        </p>
      </div>
    );
  }

  const wanted = filter.trim().toLocaleLowerCase(locale);
  const rows = documents.data.filter(
    (document) =>
      (shown === "all" || groupOf(document.status) === shown) &&
      (wanted === "" ||
        [document.title, document.kind, document.reference, ...(document.tags ?? [])].some(
          (text) => text != null && text.toLocaleLowerCase(locale).includes(wanted),
        )),
  );

  const counts: Record<Shown, number> = {
    all: documents.data.length,
    ready: 0,
    working: 0,
    failed: 0,
  };
  for (const document of documents.data) counts[groupOf(document.status)] += 1;

  return (
    <div className="@container flex flex-col gap-3">
      {/* How many documents are in each state, and what that state means; each card also
          shows only its documents. */}
      <div
        role="group"
        aria-label={m.library_filter_label()}
        className="grid grid-cols-2 gap-2.5 @xl:grid-cols-4"
      >
        {FILTERS.map(([value, label, hint, tone, IconFor], index) => (
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
            <span className="flex items-center gap-1.5 text-[13px] font-medium text-subtle-foreground">
              <IconFor weight="fill" className={cn("size-4", tone)} aria-hidden="true" />
              {label()}
            </span>
            <span className="text-2xl leading-tight font-semibold tracking-tight">
              <CountUp to={counts[value]} />
            </span>
            <span className="text-xs leading-snug text-muted-foreground">{hint()}</span>
          </button>
        ))}
      </div>
      <label className="flex h-11 items-center gap-2.5 rounded-xl border border-input bg-card px-3.5 text-muted-foreground transition-[border-color,box-shadow] focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/20">
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
            <DocumentRow
              key={document.id}
              document={document}
              index={index}
              canWrite={collection.can_write}
              listKey={key}
              onOpen={onOpen}
            />
          ))}
        </ul>
      </div>
    </div>
  );
}
