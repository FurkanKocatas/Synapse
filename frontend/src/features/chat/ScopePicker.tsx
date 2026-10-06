import { Popover } from "@base-ui/react/popover";
import {
  CaretDownIcon,
  FunnelSimpleIcon,
  LockSimpleIcon,
  MagnifyingGlassIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import { useState } from "react";

import { floatingPanel } from "@/components/ui/menu";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";
import { getLocale } from "@/paraglide/runtime.js";

import {
  EVERYTHING,
  folderTree,
  isEverything,
  MAX_COLLECTIONS,
  MAX_DOCUMENTS,
  parents,
  scopeLabel,
  useScopeNames,
  type ChatScope,
} from "./scope";
import { ScopeTree } from "./ScopeTree";

/** Where the next questions are searched, under the box to ask in: a button that says it, and
 * opens a panel to choose everything the user may read, or some folders and documents. */
export function ScopePicker({
  value,
  onChange,
}: {
  value: ChatScope;
  onChange: (scope: ChatScope) => void;
}) {
  const [open, setOpen] = useState(false);
  const names = useScopeNames();
  const label = scopeLabel(value, names.names, names.titles);
  const chosen = !isEverything(value);

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger
        aria-label={m.chat_scope_button({ scope: label })}
        title={chosen ? label : m.chat_scope_hint()}
        className={cn(
          "inline-flex h-[30px] max-w-[70%] min-w-0 items-center gap-1.5 rounded-[9px] px-2.5 text-[12.5px] text-subtle-foreground outline-none transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring data-[popup-open]:bg-accent data-[popup-open]:text-foreground",
          chosen && "bg-secondary font-medium text-secondary-foreground hover:bg-secondary",
        )}
      >
        {chosen ? (
          <FunnelSimpleIcon className="size-3.5 shrink-0" aria-hidden="true" />
        ) : (
          <LockSimpleIcon className="size-3.5 shrink-0" aria-hidden="true" />
        )}
        <span className="truncate">{label}</span>
        <CaretDownIcon
          className={cn("size-3 shrink-0 transition-transform", open && "rotate-180")}
          aria-hidden="true"
        />
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Positioner side="top" align="start" sideOffset={10} collisionPadding={12}>
          <Popover.Popup
            className={cn(
              floatingPanel,
              "flex max-h-[min(36rem,var(--available-height))] w-[min(29rem,calc(100vw-1.5rem))] flex-col overflow-y-auto",
            )}
          >
            <Panel
              initial={value}
              names={names}
              onApply={(scope) => {
                onChange(scope);
                setOpen(false);
              }}
            />
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}

function Panel({
  initial,
  names,
  onApply,
}: {
  initial: ChatScope;
  names: ReturnType<typeof useScopeNames>;
  onApply: (scope: ChatScope) => void;
}) {
  const [whole, setWhole] = useState(isEverything(initial));
  const [draft, setDraft] = useState(initial);
  const [find, setFind] = useState("");
  const nodes = folderTree(names.folders);
  const up = parents(names.folders);
  const tooMany =
    draft.collections.length > MAX_COLLECTIONS || draft.documents.length > MAX_DOCUMENTS;
  const empty = isEverything(draft);

  return (
    <>
      <header className="shrink-0 border-b px-4 pt-3.5 pb-3">
        <Popover.Title className="text-[15px] font-semibold">{m.chat_scope_title()}</Popover.Title>
        <Popover.Description className="mt-0.5 mb-2.5 text-[12.5px] text-muted-foreground">
          {m.chat_scope_lead()}
        </Popover.Description>
        <div
          role="radiogroup"
          aria-label={m.chat_scope_title()}
          className="grid grid-cols-2 gap-1.5"
        >
          <Choice
            on={whole}
            title={m.chat_scope_everything()}
            detail={m.chat_scope_everything_detail()}
            onPick={() => {
              setWhole(true);
            }}
          />
          <Choice
            on={!whole}
            title={m.chat_scope_chosen()}
            detail={m.chat_scope_chosen_detail()}
            onPick={() => {
              setWhole(false);
            }}
          />
        </div>
      </header>
      {!whole && (
        <>
          <label className="mx-4 mt-2.5 mb-1.5 flex h-[34px] shrink-0 items-center gap-2 rounded-[9px] border border-input px-2.5 text-muted-foreground focus-within:border-ring">
            <MagnifyingGlassIcon className="size-4 shrink-0" aria-hidden="true" />
            <input
              type="search"
              value={find}
              aria-label={m.chat_scope_find()}
              placeholder={m.chat_scope_find()}
              onChange={(event) => {
                setFind(event.target.value);
              }}
              className="min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
            />
          </label>
          <div className="min-h-28 flex-1 overflow-y-auto px-2 pb-2">
            {names.folders.length === 0 ? (
              <p className="px-3 py-4 text-sm text-muted-foreground">{m.chat_scope_no_folders()}</p>
            ) : (
              <ScopeTree
                nodes={nodes}
                draft={draft}
                onDraft={setDraft}
                find={find.trim().toLocaleLowerCase(getLocale())}
                up={up}
                folderOf={names.folderOf}
              />
            )}
          </div>
          <p className="shrink-0 px-4 pb-2 text-xs text-muted-foreground">{m.chat_scope_note()}</p>
          {tooMany && (
            <p className="mx-4 mb-2 flex shrink-0 items-center gap-1.5 text-xs text-destructive">
              <WarningCircleIcon weight="fill" className="size-4 shrink-0" aria-hidden="true" />
              {m.chat_scope_too_many({
                folders: String(MAX_COLLECTIONS),
                documents: String(MAX_DOCUMENTS),
              })}
            </p>
          )}
        </>
      )}
      <footer className="flex shrink-0 items-center gap-2 border-t bg-sidebar px-4 py-2.5">
        <span className="min-w-0 flex-1 truncate text-[12.5px] text-subtle-foreground">
          {whole
            ? m.chat_scope_everything_detail()
            : empty
              ? m.chat_scope_nothing()
              : m.chat_scope_selected({
                  scope: scopeLabel(draft, names.names, names.titles),
                })}
        </span>
        {!whole && (
          <button
            type="button"
            disabled={empty}
            onClick={() => {
              setDraft(EVERYTHING);
            }}
            className="h-8 shrink-0 rounded-[9px] border border-input bg-card px-3 text-sm font-medium outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
          >
            {m.chat_scope_clear()}
          </button>
        )}
        <button
          type="button"
          disabled={!whole && (empty || tooMany)}
          onClick={() => {
            onApply(whole ? EVERYTHING : draft);
          }}
          className="h-8 shrink-0 rounded-[9px] bg-primary px-3 text-sm font-medium text-primary-foreground outline-none hover:bg-primary-hover focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
        >
          {whole ? m.chat_scope_apply_everything() : m.chat_scope_apply()}
        </button>
      </footer>
    </>
  );
}

function Choice({
  on,
  title,
  detail,
  onPick,
}: {
  on: boolean;
  title: string;
  detail: string;
  onPick: () => void;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={on}
      onClick={onPick}
      className={cn(
        "flex items-start gap-2 rounded-[10px] border px-2.5 py-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring",
        on && "border-primary bg-secondary",
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "relative mt-0.5 size-[15px] shrink-0 rounded-full border-[1.5px] border-input",
          on &&
            "border-primary after:absolute after:inset-[3px] after:rounded-full after:bg-primary",
        )}
      />
      <span className="min-w-0">
        <b className="block text-[13px] font-semibold">{title}</b>
        <small className="text-[11.5px] text-muted-foreground">{detail}</small>
      </span>
    </button>
  );
}
