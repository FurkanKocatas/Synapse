import { Dialog } from "@base-ui/react/dialog";
import { MagicWandIcon, XIcon } from "@phosphor-icons/react";
import { useState, type KeyboardEvent, type ReactNode, type SubmitEvent } from "react";

import { FormError } from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { dialogBackdrop } from "@/components/ui/menu";
import { useAction } from "@/lib/useAction";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";

import { libraryApi, type LibraryDocument, type MetadataChange } from "./libraryApi";

// Kinds offered in the list; any other can be written. The same words the server suggests
// from (backend/src/synapse/knowledge/data/language_tr.json, document_kinds).
const KINDS = [
  "Karar",
  "Kararname",
  "Yönetmelik",
  "Yönerge",
  "Genelge",
  "Tebliğ",
  "Kanun",
  "Tüzük",
  "Rapor",
  "Sözleşme",
  "Tutanak",
  "Protokol",
  "Şartname",
  "Kılavuz",
  "Rehber",
  "Dilekçe",
  "Duyuru",
  "Bülten",
  "Yıllık",
];
const MAX_TAGS = 20;
const MAX_TAG = 50;

/** A document's details: its name, kind, date, number and tags, with what was found on its
 * first page marked so, to be checked and corrected. */
export function MetadataDialog({
  document,
  open,
  listKey,
  onClose,
}: {
  document: LibraryDocument;
  open: boolean;
  // The list to refresh once saved.
  listKey: string[];
  onClose: () => void;
}) {
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Backdrop className={dialogBackdrop} />
        <Dialog.Popup className="fixed top-[7vh] left-1/2 z-50 max-h-[86vh] w-[min(32rem,calc(100vw-2rem))] -translate-x-1/2 overflow-y-auto rounded-2xl border bg-popover text-popover-foreground shadow-floating outline-none transition-[opacity,scale] duration-200 ease-out-soft data-[ending-style]:scale-97 data-[ending-style]:opacity-0 data-[starting-style]:scale-97 data-[starting-style]:opacity-0">
          <Dialog.Title className="px-5 pt-5 text-[17px] font-semibold">
            {m.library_info_title()}
          </Dialog.Title>
          <Dialog.Description className="truncate px-5 pt-1 text-sm text-muted-foreground">
            {document.title}
          </Dialog.Description>
          <MetadataForm document={document} listKey={listKey} onDone={onClose} />
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// Its own component, so it starts from the document as it is each time the dialog opens.
function MetadataForm({
  document,
  listKey,
  onDone,
}: {
  document: LibraryDocument;
  listKey: string[];
  onDone: () => void;
}) {
  const [title, setTitle] = useState(document.title);
  const [kind, setKind] = useState(document.kind ?? "");
  const [date, setDate] = useState(document.document_date ?? "");
  const [reference, setReference] = useState(document.reference ?? "");
  const [tags, setTags] = useState<string[]>(document.tags ?? []);
  const [tag, setTag] = useState("");
  const { run, error, busy } = useAction();
  const byHand = new Set(document.set_by_hand ?? []);
  // Found on the page and not changed by anyone yet, nor in this form.
  const found = {
    kind: document.kind != null && !byHand.has("kind") && kind === document.kind,
    document_date:
      document.document_date != null &&
      !byHand.has("document_date") &&
      date === document.document_date,
    reference:
      document.reference != null && !byHand.has("reference") && reference === document.reference,
  };

  function addTag() {
    const text = tag.split(/\s+/).filter(Boolean).join(" ").slice(0, MAX_TAG);
    if (text !== "" && !tags.includes(text) && tags.length < MAX_TAGS) setTags([...tags, text]);
    setTag("");
  }

  function onTagKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      addTag();
    } else if (event.key === "Backspace" && tag === "" && tags.length > 0) {
      setTags(tags.slice(0, -1));
    }
  }

  async function save(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const pending = tag.trim() === "" ? tags : [...tags, tag.trim()];
    const changes: MetadataChange = {};
    if (title.trim() !== document.title) changes.title = title.trim();
    if (kind.trim() !== (document.kind ?? "")) changes.kind = kind.trim() || null;
    if (date !== (document.document_date ?? "")) changes.document_date = date || null;
    if (reference.trim() !== (document.reference ?? "")) {
      changes.reference = reference.trim() || null;
    }
    if (pending.join("\n") !== (document.tags ?? []).join("\n")) changes.tags = pending;
    if (Object.keys(changes).length === 0) {
      onDone();
      return;
    }
    if (await run(() => libraryApi.updateMetadata(document.id, changes), [listKey])) onDone();
  }

  return (
    <form className="flex flex-col gap-4 px-5 pt-4 pb-5" onSubmit={(event) => void save(event)}>
      {(found.kind || found.document_date || found.reference) && (
        <p className="flex gap-2.5 rounded-xl bg-warning/12 px-3 py-2.5 text-[13px] text-foreground">
          <MagicWandIcon weight="fill" className="mt-0.5 size-4 shrink-0 text-warning" />
          {m.library_info_found()}
        </p>
      )}
      <Field id="document-title" label={m.library_field_title()}>
        <Input
          id="document-title"
          value={title}
          maxLength={500}
          onChange={(event) => {
            setTitle(event.target.value);
          }}
        />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          id="document-kind"
          label={m.library_field_kind()}
          found={found.kind}
          help={m.library_field_kind_help()}
        >
          <Input
            id="document-kind"
            list="document-kinds"
            value={kind}
            maxLength={80}
            onChange={(event) => {
              setKind(event.target.value);
            }}
          />
          <datalist id="document-kinds">
            {KINDS.map((k) => (
              <option key={k} value={k} />
            ))}
          </datalist>
        </Field>
        <Field id="document-date" label={m.library_field_date()} found={found.document_date}>
          <Input
            id="document-date"
            type="date"
            value={date}
            onChange={(event) => {
              setDate(event.target.value);
            }}
          />
        </Field>
        <Field id="document-reference" label={m.library_field_reference()} found={found.reference}>
          <Input
            id="document-reference"
            value={reference}
            maxLength={120}
            onChange={(event) => {
              setReference(event.target.value);
            }}
          />
        </Field>
      </div>
      <Field id="document-tag" label={m.library_field_tags()} help={m.library_tags_help()}>
        <div className="flex min-h-9 flex-wrap items-center gap-1.5 rounded-lg border border-input bg-card px-2 py-1.5 focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/20">
          {tags.map((t) => (
            <span
              key={t}
              className="inline-flex h-6 items-center gap-1 rounded-full bg-secondary pr-1 pl-2.5 text-xs font-medium text-secondary-foreground"
            >
              {t}
              <button
                type="button"
                aria-label={m.library_remove_tag({ tag: t })}
                onClick={() => {
                  setTags(tags.filter((other) => other !== t));
                }}
                className="inline-flex size-4 items-center justify-center rounded-full outline-none hover:bg-secondary-foreground/15 focus-visible:ring-2 focus-visible:ring-ring"
              >
                <XIcon weight="bold" className="size-2.5" aria-hidden="true" />
              </button>
            </span>
          ))}
          <input
            id="document-tag"
            value={tag}
            maxLength={MAX_TAG}
            disabled={tags.length >= MAX_TAGS}
            placeholder={m.library_tags_placeholder()}
            onChange={(event) => {
              setTag(event.target.value);
            }}
            onKeyDown={onTagKey}
            onBlur={addTag}
            className="h-6 min-w-24 flex-1 bg-transparent px-1 text-sm outline-none placeholder:text-muted-foreground"
          />
        </div>
      </Field>
      <FormError message={error} />
      <div className="flex justify-end gap-2">
        <Dialog.Close render={<Button type="button" variant="outline" />}>
          {m.common_cancel()}
        </Dialog.Close>
        <Button type="submit" disabled={busy || title.trim() === ""}>
          {m.chat_save()}
        </Button>
      </div>
    </form>
  );
}

function Field({
  id,
  label,
  found = false,
  help,
  children,
}: {
  id: string;
  label: string;
  found?: boolean;
  help?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id} className="flex items-center gap-1.5">
        {label}
        {found && (
          <span className="rounded-full bg-warning/15 px-2 py-px text-[11px] font-medium text-foreground">
            {m.library_found_badge()}
          </span>
        )}
      </Label>
      {children}
      {help !== undefined && <span className={cn("text-xs text-muted-foreground")}>{help}</span>}
    </div>
  );
}
