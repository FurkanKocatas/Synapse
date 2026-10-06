import {
  ArrowsLeftRightIcon,
  PencilSimpleIcon,
  PlusIcon,
  TrashIcon,
  WarningCircleIcon,
  XIcon,
} from "@phosphor-icons/react";
import { useState, type KeyboardEvent } from "react";

import { FormError } from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/IconButton";
import { useAction } from "@/lib/useAction";
import { m } from "@/paraglide/messages.js";
import { getLocale } from "@/paraglide/runtime.js";

import { adminApi, SETTINGS_KEY, type OrganizationSettings } from "./adminApi";
import { SettingsCard } from "./SettingsCard";

// The server's limits (organization/settings.py).
const MIN_PHRASES = 2;
const MAX_PHRASES = 10;
const MAX_PHRASE = 100;

function fold(text: string): string {
  return text.toLocaleLowerCase(getLocale());
}

/** Groups of words that mean the same, abbreviations among them: a question that has one is
 * searched for with the others too. Each group is added, changed or removed on its own. */
export function SynonymsCard({ settings }: { settings: OrganizationSettings }) {
  const groups = settings.synonyms;
  // The group being written: a new one, or ``editing`` (its place in the list) changed.
  const [phrases, setPhrases] = useState<string[]>([]);
  const [typed, setTyped] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const { run, error, busy } = useAction();

  // What was typed without Enter counts too, so the group button takes it.
  const word = typed.split(/\s+/).filter(Boolean).join(" ");
  const pending =
    word === "" || phrases.some((p) => fold(p) === fold(word)) ? phrases : [...phrases, word];
  const others = groups.flatMap((group, index) => (index === editing ? [] : group)).map(fold);
  const taken = pending.find((phrase) => others.includes(fold(phrase)));
  const ready = pending.length >= MIN_PHRASES && pending.length <= MAX_PHRASES && !taken;

  function addPhrase() {
    const text = typed.split(/\s+/).filter(Boolean).join(" ");
    if (
      text !== "" &&
      !phrases.some((p) => fold(p) === fold(text)) &&
      phrases.length < MAX_PHRASES
    ) {
      setPhrases([...phrases, text]);
    }
    setTyped("");
  }

  function onKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      addPhrase();
    } else if (event.key === "Backspace" && typed === "" && phrases.length > 0) {
      setPhrases(phrases.slice(0, -1));
    }
  }

  async function store(next: string[][]) {
    return run(() => adminApi.changeSettings({ synonyms: next }), [SETTINGS_KEY]);
  }

  async function saveGroup() {
    const next =
      editing === null
        ? [...groups, pending]
        : groups.map((group, index) => (index === editing ? pending : group));
    if (await store(next)) {
      setPhrases([]);
      setTyped("");
      setEditing(null);
    }
  }

  return (
    <SettingsCard
      icon={ArrowsLeftRightIcon}
      title={m.settings_synonyms_title()}
      lead={m.settings_synonyms_lead()}
    >
      <p className="mb-3 rounded-xl bg-sidebar px-3 py-2.5 text-[13px] text-subtle-foreground">
        {m.settings_synonyms_example()}
      </p>
      <p className="mb-2 text-xs text-muted-foreground">
        {m.settings_synonyms_count({ count: String(groups.length) })}
      </p>
      {groups.length === 0 ? (
        <p className="rounded-xl border border-dashed px-3 py-4 text-sm text-muted-foreground">
          {m.settings_synonyms_empty()}
        </p>
      ) : (
        <ul className="divide-y rounded-xl border">
          {groups.map((group, index) => (
            <li key={group.join("\n")} className="flex items-center gap-2 py-2 pr-2 pl-3">
              <span className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
                {group.map((phrase, at) => (
                  <span key={phrase} className="contents">
                    {at > 0 && (
                      <span aria-hidden="true" className="text-sm text-muted-foreground">
                        =
                      </span>
                    )}
                    <span className="rounded-full bg-secondary px-2.5 py-0.5 text-[12.5px] font-medium text-secondary-foreground">
                      {phrase}
                    </span>
                  </span>
                ))}
              </span>
              <IconButton
                label={`${m.settings_synonyms_edit()}: ${group.join(", ")}`}
                onClick={() => {
                  setEditing(index);
                  setPhrases(group);
                  setTyped("");
                }}
              >
                <PencilSimpleIcon aria-hidden="true" />
              </IconButton>
              <IconButton
                className="hover:text-destructive"
                label={`${m.settings_synonyms_remove()}: ${group.join(", ")}`}
                disabled={busy}
                onClick={() => {
                  if (editing === index) {
                    setEditing(null);
                    setPhrases([]);
                  }
                  void store(groups.filter((_, other) => other !== index));
                }}
              >
                <TrashIcon aria-hidden="true" />
              </IconButton>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-start">
        <div className="flex min-h-10 flex-1 flex-wrap items-center gap-1.5 rounded-xl border border-input bg-card px-2 py-1.5 focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/20">
          {phrases.map((phrase) => (
            <span
              key={phrase}
              className="inline-flex h-6 items-center gap-1 rounded-full bg-secondary pr-1 pl-2.5 text-xs font-medium text-secondary-foreground"
            >
              {phrase}
              <button
                type="button"
                aria-label={m.settings_synonyms_remove_phrase({ phrase })}
                onClick={() => {
                  setPhrases(phrases.filter((other) => other !== phrase));
                }}
                className="inline-flex size-4 items-center justify-center rounded-full outline-none hover:bg-secondary-foreground/15 focus-visible:ring-2 focus-visible:ring-ring"
              >
                <XIcon weight="bold" className="size-2.5" aria-hidden="true" />
              </button>
            </span>
          ))}
          <input
            value={typed}
            maxLength={MAX_PHRASE}
            aria-label={m.settings_synonyms_placeholder()}
            placeholder={phrases.length === 0 ? m.settings_synonyms_placeholder() : ""}
            disabled={phrases.length >= MAX_PHRASES}
            onChange={(event) => {
              setTyped(event.target.value);
            }}
            onKeyDown={onKey}
            className="h-7 min-w-32 flex-1 bg-transparent px-1 text-sm outline-none placeholder:text-muted-foreground"
          />
        </div>
        <div className="flex shrink-0 gap-2">
          {editing !== null && (
            <Button
              variant="outline"
              onClick={() => {
                setEditing(null);
                setPhrases([]);
              }}
            >
              {m.common_cancel()}
            </Button>
          )}
          <Button
            variant={ready ? "default" : "outline"}
            disabled={!ready || busy}
            onClick={() => void saveGroup()}
          >
            <PlusIcon aria-hidden="true" />
            {editing === null ? m.settings_synonyms_add() : m.settings_synonyms_save()}
          </Button>
        </div>
      </div>
      {taken !== undefined ? (
        <p
          role="alert"
          className="mt-2 flex items-center gap-1.5 rounded-lg bg-destructive/10 px-3 py-2 text-[12.5px] text-destructive"
        >
          <WarningCircleIcon weight="fill" className="size-4 shrink-0" aria-hidden="true" />
          {m.settings_synonyms_taken({ phrase: taken })}
        </p>
      ) : (
        <p className="mt-1.5 text-xs text-muted-foreground">{m.settings_synonyms_help()}</p>
      )}
      <FormError message={error} />
    </SettingsCard>
  );
}
