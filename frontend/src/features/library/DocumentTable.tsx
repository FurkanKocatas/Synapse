import { useQuery } from "@tanstack/react-query";
import { Download, FileText, Trash2 } from "lucide-react";
import { useState } from "react";

import { FormError } from "@/components/AuthLayout";
import { Button, buttonVariants } from "@/components/ui/button";
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
// A dot per status: ready green, in progress amber, failed red, parsed (searchable by words) blue.
const STATUS_DOT: Record<LibraryDocument["status"], string> = {
  queued: "bg-highlight",
  parsing: "bg-highlight",
  ocr: "bg-highlight",
  embedding: "bg-highlight",
  parsed: "bg-chart-2",
  ready: "bg-chart-5",
  failed: "bg-destructive",
};

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
  const locale = getLocale();
  const dates = new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" });

  if (documents.data === undefined) {
    return <p className="text-sm text-muted-foreground">{m.common_loading()}</p>;
  }
  if (documents.data.length === 0) {
    return <p className="text-sm text-muted-foreground">{m.library_empty()}</p>;
  }

  function remove(document: LibraryDocument) {
    setConfirming(null);
    void run(() => libraryApi.remove(document.id), [key]);
  }

  return (
    <div className="flex flex-col gap-2">
      <FormError message={error} />
      <p className="px-1 text-xs text-muted-foreground">
        {m.library_count({ count: String(documents.data.length) })}
      </p>
      <ul className="flex flex-col divide-y overflow-hidden rounded-xl border bg-card">
        {documents.data.map((document) => (
          <li key={document.id} className="flex items-center gap-3 px-3 py-2.5 sm:px-4">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <FileText className="size-4" aria-hidden="true" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium" title={document.title}>
                {document.title}
              </p>
              <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-1.5">
                  <span
                    aria-hidden="true"
                    className={cn("size-1.5 rounded-full", STATUS_DOT[document.status])}
                  />
                  {statusLabel[document.status]()}
                </span>
                <span aria-hidden="true">·</span>
                <span className="tabular-nums">{formatSize(document.size_bytes, locale)}</span>
                <span aria-hidden="true">·</span>
                <span>{dates.format(new Date(document.updated_at))}</span>
              </p>
              {document.status === "failed" && (
                <p className="text-xs text-destructive">{failureText(document.failure)}</p>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <a
                className={buttonVariants({ variant: "ghost", size: "icon-sm" })}
                href={libraryApi.fileUrl(document.id, document.latest_version)}
                aria-label={`${m.library_download()}: ${document.title}`}
                title={m.library_download()}
              >
                <Download className="size-4" aria-hidden="true" />
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
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    disabled={busy}
                    aria-label={`${m.library_delete()}: ${document.title}`}
                    title={m.library_delete()}
                    onClick={() => {
                      setConfirming(document.id);
                    }}
                  >
                    <Trash2 className="size-4" aria-hidden="true" />
                  </Button>
                ))}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
