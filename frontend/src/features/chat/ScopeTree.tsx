import {
  CaretRightIcon,
  CheckIcon,
  FileTextIcon,
  FolderIcon,
  FolderOpenIcon,
  MinusIcon,
} from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { libraryApi } from "@/features/library/libraryApi";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";
import { getLocale } from "@/paraglide/runtime.js";

import {
  covered,
  documentsKey,
  folderMark,
  toggleDocument,
  toggleFolder,
  type ChatScope,
  type FolderNode,
  type Mark,
} from "./scope";

interface TreeProps {
  draft: ChatScope;
  onDraft: (scope: ChatScope) => void;
  // Lower-cased; empty shows everything.
  find: string;
  up: Map<string, string | null>;
  folderOf: Map<string, string>;
}

/** The folders the user can see, as a tree, each with a box to choose it and, opened, the
 * folders and documents inside it to choose one by one. */
export function ScopeTree({ nodes, ...props }: TreeProps & { nodes: FolderNode[] }) {
  const shown = nodes.filter((node) => matches(node, props.find));
  if (shown.length === 0) {
    return <p className="px-3 py-4 text-sm text-muted-foreground">{m.chat_scope_no_match()}</p>;
  }
  return (
    <ul role="tree" aria-label={m.chat_scope_title()} className="flex flex-col gap-px">
      {shown.map((node) => (
        <FolderRow key={node.folder.id} node={node} {...props} />
      ))}
    </ul>
  );
}

function lower(text: string): string {
  return text.toLocaleLowerCase(getLocale());
}

function matches(node: FolderNode, find: string): boolean {
  return (
    find === "" ||
    lower(node.folder.name).includes(find) ||
    node.children.some((child) => matches(child, find))
  );
}

function FolderRow({ node, ...props }: TreeProps & { node: FolderNode }) {
  const { draft, onDraft, find, up, folderOf } = props;
  const [opened, setOpened] = useState(false);
  // A search opens the folders on the way to what it found.
  const open = opened || (find !== "" && node.children.some((child) => matches(child, find)));
  const count = node.folder.document_count ?? 0;
  const documents = useQuery({
    queryKey: documentsKey(node.folder.id),
    queryFn: () => libraryApi.documents(node.folder.id),
    enabled: open && count > 0,
  });
  const mark = folderMark(draft, node, up, folderOf);
  const inherited = mark === "inherited";
  const picked = draft.documents.filter((d) => folderOf.get(d) === node.folder.id).length;
  const openable = node.children.length > 0 || count > 0;
  const shownDocuments = (documents.data ?? []).filter(
    (d) => find === "" || lower(d.title).includes(find),
  );

  return (
    <li role="treeitem" aria-expanded={openable ? open : undefined} aria-selected={false}>
      <div
        className="flex h-9 items-center gap-1.5 rounded-lg pr-2 hover:bg-accent"
        style={{ paddingLeft: `${String(4 + node.depth * 22)}px` }}
      >
        <button
          type="button"
          tabIndex={openable ? 0 : -1}
          aria-label={open ? m.chat_scope_close_folder() : m.chat_scope_open_folder()}
          disabled={!openable}
          onClick={() => {
            setOpened(!open);
          }}
          className="inline-flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:invisible"
        >
          <CaretRightIcon
            className={cn("size-3.5 transition-transform", open && "rotate-90")}
            aria-hidden="true"
          />
        </button>
        <Box
          mark={mark}
          label={node.folder.name}
          disabled={inherited}
          onToggle={() => {
            onDraft(toggleFolder(draft, node, folderOf));
          }}
        />
        {open ? (
          <FolderOpenIcon weight="fill" className="size-4 shrink-0 text-secondary-foreground" />
        ) : (
          <FolderIcon weight="fill" className="size-4 shrink-0 text-secondary-foreground" />
        )}
        <span className="min-w-0 flex-1 truncate text-sm">{node.folder.name}</span>
        {count > 0 && (
          <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
            {picked > 0
              ? m.chat_scope_picked_of({ picked: String(picked), count: String(count) })
              : m.chat_scope_documents({ count: String(count) })}
          </span>
        )}
      </div>
      {open && (
        <ul role="group" className="flex flex-col gap-px">
          {node.children
            .filter((child) => matches(child, find))
            .map((child) => (
              <FolderRow key={child.folder.id} node={child} {...props} />
            ))}
          {documents.isPending && count > 0 && (
            <li
              className="py-1.5 text-xs text-muted-foreground"
              style={{ paddingLeft: `${String(62 + node.depth * 22)}px` }}
            >
              {m.common_loading()}
            </li>
          )}
          {shownDocuments.map((document) => {
            const on = draft.documents.includes(document.id) || covered(draft, node.folder.id, up);
            return (
              <li key={document.id} role="treeitem" aria-selected={false}>
                <div
                  className="flex h-9 items-center gap-1.5 rounded-lg pr-2 hover:bg-accent"
                  style={{ paddingLeft: `${String(34 + node.depth * 22)}px` }}
                >
                  <Box
                    mark={on ? (draft.documents.includes(document.id) ? "on" : "inherited") : "off"}
                    label={document.title}
                    disabled={covered(draft, node.folder.id, up)}
                    onToggle={() => {
                      onDraft(toggleDocument(draft, document.id));
                    }}
                  />
                  <FileTextIcon className="size-4 shrink-0 text-subtle-foreground" />
                  <span className="min-w-0 flex-1 truncate text-sm">{document.title}</span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </li>
  );
}

/** A box to choose a folder or a document: chosen, chosen through the folder above it (shown
 * chosen, not to be unticked here), partly chosen, or not. */
function Box({
  mark,
  label,
  disabled,
  onToggle,
}: {
  mark: Mark;
  label: string;
  disabled: boolean;
  onToggle: () => void;
}) {
  const ticked = mark === "on" || mark === "inherited";
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={mark === "part" ? "mixed" : ticked}
      aria-label={label}
      disabled={disabled}
      onClick={onToggle}
      className={cn(
        "inline-flex size-[18px] shrink-0 items-center justify-center rounded-[5px] border-[1.5px] border-input text-primary-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring",
        (ticked || mark === "part") && "border-primary bg-primary",
        mark === "inherited" && "opacity-60",
      )}
    >
      {ticked && <CheckIcon weight="bold" className="size-3" aria-hidden="true" />}
      {mark === "part" && <MinusIcon weight="bold" className="size-3" aria-hidden="true" />}
    </button>
  );
}
