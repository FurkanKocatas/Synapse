import { AlertDialog } from "@base-ui/react/alert-dialog";
import {
  CheckCircleIcon,
  CircleNotchIcon,
  DownloadSimpleIcon,
  EyeIcon,
  TrashIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import { useState, type CSSProperties } from "react";

import { FormError } from "@/components/AuthLayout";
import { Button, buttonVariants } from "@/components/ui/button";
import { IconButton } from "@/components/ui/IconButton";
import { dialogBackdrop, dialogPopup } from "@/components/ui/menu";
import { FileIcon } from "@/lib/fileKind";
import { useAction } from "@/lib/useAction";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";
import { getLocale } from "@/paraglide/runtime.js";

import { failureText, formatSize, statusLabel } from "./labels";
import { IN_PROGRESS, libraryApi, type LibraryDocument } from "./libraryApi";

// By the width of the list itself (container queries), not the window: beside the
// navigation and the folders the list can be narrow on a wide screen.
export const COLUMNS =
  "grid grid-cols-[minmax(0,1fr)_auto] @2xl:grid-cols-[minmax(0,1fr)_10rem_5.5rem_10rem_6.5rem]";

// Statuses whose pages can be shown: the document has been read.
const OPENABLE: ReadonlySet<LibraryDocument["status"]> = new Set(["parsed", "embedding", "ready"]);

/** One document of the list: its name (which opens it), what state it is in, in words and a
 * colour, and what can be done with it. */
export function DocumentRow({
  document,
  index,
  canWrite,
  listKey,
  onOpen,
}: {
  document: LibraryDocument;
  index: number;
  canWrite: boolean;
  // The list to refresh once the document is deleted.
  listKey: string[];
  onOpen: (document: LibraryDocument) => void;
}) {
  const [deleting, setDeleting] = useState(false);
  const locale = getLocale();
  const dates = new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" });
  const openable = OPENABLE.has(document.status);
  const note =
    document.status === "failed"
      ? failureText(document.failure)
      : document.status === "ocr"
        ? m.library_ocr_note()
        : null;

  return (
    <li
      style={{ "--i": index } as CSSProperties}
      className={cn(
        COLUMNS,
        "min-h-14 animate-rise items-center gap-x-3 px-4 py-2.5 transition-colors hover:bg-background",
      )}
    >
      <div className="flex min-w-0 items-center gap-3">
        <FileIcon mediaType={document.media_type} name={document.title} />
        <div className="min-w-0">
          {openable ? (
            <button
              type="button"
              title={document.title}
              onClick={() => {
                onOpen(document);
              }}
              className="block max-w-full truncate text-left text-[14.5px] font-medium underline-offset-4 outline-none hover:underline focus-visible:underline"
            >
              {document.title}
            </button>
          ) : (
            <p className="truncate text-[14.5px] font-medium" title={document.title}>
              {document.title}
            </p>
          )}
          {note !== null && (
            <p
              className={cn(
                "text-xs",
                document.status === "failed" ? "text-destructive" : "text-muted-foreground",
              )}
            >
              {note}
            </p>
          )}
          <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground @2xl:hidden">
            <StatusPill status={document.status} />
            {formatSize(document.size_bytes, locale)}
          </p>
        </div>
      </div>
      <span className="hidden @2xl:block">
        <StatusPill status={document.status} />
      </span>
      <span className="hidden text-xs text-subtle-foreground tabular-nums @2xl:block">
        {formatSize(document.size_bytes, locale)}
      </span>
      <span className="hidden text-xs text-subtle-foreground @2xl:block">
        {dates.format(new Date(document.updated_at))}
      </span>
      <div className="flex shrink-0 items-center justify-end gap-0.5">
        {openable && (
          <IconButton
            label={`${m.library_open()}: ${document.title}`}
            onClick={() => {
              onOpen(document);
            }}
          >
            <EyeIcon aria-hidden="true" />
          </IconButton>
        )}
        <a
          className={buttonVariants({ variant: "ghost", size: "icon-sm" })}
          href={libraryApi.fileUrl(document.id, document.latest_version)}
          aria-label={`${m.library_download()}: ${document.title}`}
          title={m.library_download()}
        >
          <DownloadSimpleIcon className="size-4" aria-hidden="true" />
        </a>
        {canWrite && (
          <IconButton
            className="hover:text-destructive"
            label={`${m.library_delete()}: ${document.title}`}
            onClick={() => {
              setDeleting(true);
            }}
          >
            <TrashIcon aria-hidden="true" />
          </IconButton>
        )}
      </div>
      {canWrite && (
        <DeleteDialog
          open={deleting}
          document={document}
          listKey={listKey}
          onClose={() => {
            setDeleting(false);
          }}
        />
      )}
    </li>
  );
}

/** The state in a word with an icon and a colour: ready green, getting ready amber (turning),
 * a problem red. */
function StatusPill({ status }: { status: LibraryDocument["status"] }) {
  const working = IN_PROGRESS.has(status);
  const failed = status === "failed";
  const Icon = failed ? WarningCircleIcon : working ? CircleNotchIcon : CheckCircleIcon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap",
        failed
          ? "bg-destructive/10 text-destructive"
          : working
            ? "bg-warning/15 text-foreground"
            : "bg-success/12 text-foreground",
      )}
    >
      <Icon
        weight={working ? "bold" : "fill"}
        className={cn(
          "size-3.5 shrink-0",
          failed ? "text-destructive" : working ? "animate-spin text-warning" : "text-success",
        )}
        aria-hidden="true"
      />
      {statusLabel[status]()}
    </span>
  );
}

function DeleteDialog({
  open,
  document,
  listKey,
  onClose,
}: {
  open: boolean;
  document: LibraryDocument;
  listKey: string[];
  onClose: () => void;
}) {
  const { run, error, busy } = useAction();

  async function remove() {
    if (await run(() => libraryApi.remove(document.id), [listKey])) onClose();
  }

  return (
    <AlertDialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <AlertDialog.Portal>
        <AlertDialog.Backdrop className={dialogBackdrop} />
        <AlertDialog.Popup className={dialogPopup}>
          <AlertDialog.Title className="font-medium">{m.library_delete_title()}</AlertDialog.Title>
          <AlertDialog.Description className="mt-1.5 text-sm text-muted-foreground">
            {m.library_delete_explain()}
          </AlertDialog.Description>
          <p className="mt-3 truncate rounded-lg bg-muted px-3 py-2 text-sm">{document.title}</p>
          <div className="mt-2">
            <FormError message={error} />
          </div>
          <div className="mt-3 flex justify-end gap-2">
            <AlertDialog.Close render={<Button type="button" variant="outline" />}>
              {m.common_cancel()}
            </AlertDialog.Close>
            <Button variant="destructive" disabled={busy} onClick={() => void remove()}>
              {m.library_delete_confirm()}
            </Button>
          </div>
        </AlertDialog.Popup>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
