import { useQuery, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { ArrowUp, MessageSquareText, Pencil, Plus, Search, Square, Trash2 } from "lucide-react";
import { useState, type SubmitEvent } from "react";

import { AppShell } from "@/components/AppShell";
import { FormError } from "@/components/AuthLayout";
import { LogoMark } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { sessionQuery } from "@/features/auth/session";
import { useAction } from "@/lib/useAction";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";

import { chatApi, type Conversation, type ConversationSummary, type Source } from "./chatApi";
import { DocumentViewer } from "./DocumentViewer";
import { fromLive, fromStored, TurnView } from "./TurnView";
import { isRunning, useLiveTurn } from "./useLiveTurn";

const LIST_KEY = ["chat", "conversations"];
const MAX_QUESTION = 1000;
const DAY = 24 * 60 * 60 * 1000;
const EXAMPLES = [m.chat_example_budget, m.chat_example_council, m.chat_example_retention];

function conversationKey(id: string | undefined) {
  return ["chat", "conversation", id ?? "new"];
}

/** The home page: one box to ask in, the conversation so far, and past conversations. */
export function ChatPage() {
  const { data: session } = useSuspenseQuery(sessionQuery);
  const { c: conversationId } = useSearch({ from: "/" });
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const conversations = useQuery({ queryKey: LIST_KEY, queryFn: chatApi.conversations });
  const conversation = useQuery({
    queryKey: conversationKey(conversationId),
    queryFn: () => chatApi.conversation(conversationId ?? ""),
    enabled: conversationId !== undefined,
  });
  const live = useLiveTurn({
    onTurn: (id) => {
      if (id !== conversationId) void navigate({ to: "/", search: { c: id }, replace: true });
    },
    onDone: async (id) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: LIST_KEY }),
        id === null ? null : queryClient.invalidateQueries({ queryKey: conversationKey(id) }),
      ]);
    },
  });
  const [viewing, setViewing] = useState<Source | null>(null);
  const running = isRunning(live.turn);

  function open(id: string | undefined) {
    live.clear();
    setViewing(null);
    void navigate({ to: "/", search: id === undefined ? {} : { c: id } });
  }

  function ask(question: string) {
    void live.ask(question, conversationId ?? null);
  }

  const stored = conversation.data?.turns ?? [];
  // While a turn is live, its stored row (pending, then final) is not shown twice.
  const shownStored =
    live.turn === null ? stored : stored.filter((t) => t.ordinal !== live.turn?.ordinal);
  const empty = conversationId === undefined && live.turn === null;
  const title =
    conversationId !== undefined && conversation.data !== undefined
      ? conversation.data.title
      : m.nav_chat();

  return (
    <AppShell
      title={title}
      icon={MessageSquareText}
      pane={<ConversationPane items={conversations.data} selected={conversationId} onOpen={open} />}
      paneLabel={m.chat_conversations()}
      wide
    >
      <div className="flex min-h-full flex-col">
        {empty ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-6 px-4 py-12">
            <LogoMark className="size-14" />
            <div className="text-center">
              <h2 className="text-2xl font-semibold tracking-tight">
                {m.home_welcome({ name: session?.user?.display_name ?? "" })}
              </h2>
              <p className="mt-1 text-muted-foreground">{m.home_next()}</p>
            </div>
            <div className="w-full max-w-2xl">
              <Composer running={running} onAsk={ask} onStop={live.stop} />
            </div>
            <div className="flex max-w-2xl flex-wrap justify-center gap-2">
              {EXAMPLES.map((example) => (
                <button
                  key={example()}
                  type="button"
                  onClick={() => {
                    ask(example());
                  }}
                  className="rounded-full border bg-card px-3.5 py-1.5 text-sm text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
                >
                  {example()}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 px-4 py-6">
              {conversation.data !== undefined && conversationId !== undefined && (
                <ConversationTools
                  conversation={conversation.data}
                  onDeleted={() => {
                    open(undefined);
                  }}
                />
              )}
              {conversation.data !== undefined &&
                shownStored.map((turn) => (
                  <TurnView
                    key={turn.ordinal}
                    turn={fromStored(turn)}
                    onOpen={setViewing}
                    feedbackFor={{ conversationId: conversation.data.id, ordinal: turn.ordinal }}
                  />
                ))}
              {live.turn !== null && <TurnView turn={fromLive(live.turn)} onOpen={setViewing} />}
            </div>
            <div className="sticky bottom-0 bg-gradient-to-t from-background via-background to-transparent px-4 pt-6 pb-4">
              <div className="mx-auto w-full max-w-3xl">
                <Composer running={running} onAsk={ask} onStop={live.stop} />
              </div>
            </div>
          </>
        )}
      </div>
      {viewing !== null && (
        <DocumentViewer
          key={`${viewing.document_id}:${String(viewing.ordinal)}`}
          source={viewing}
          onClose={() => {
            setViewing(null);
          }}
        />
      )}
    </AppShell>
  );
}

/** "today", "yesterday", "this week" or "older", by the local calendar. */
function age(updatedAt: string, now: Date): () => string {
  const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const at = new Date(updatedAt).getTime();
  if (at >= midnight) return m.chat_group_today;
  if (at >= midnight - DAY) return m.chat_group_yesterday;
  if (at >= midnight - 6 * DAY) return m.chat_group_week;
  return m.chat_group_older;
}

function ConversationPane({
  items,
  selected,
  onOpen,
}: {
  items: ConversationSummary[] | undefined;
  selected: string | undefined;
  onOpen: (id: string | undefined) => void;
}) {
  const [filter, setFilter] = useState("");
  const wanted = filter.trim().toLocaleLowerCase();
  const shown = (items ?? []).filter(
    (item) => wanted === "" || item.title.toLocaleLowerCase().includes(wanted),
  );
  const now = new Date();
  const groups: { label: string; items: ConversationSummary[] }[] = [];
  for (const item of shown) {
    const label = age(item.updated_at, now)();
    const last = groups.at(-1);
    if (last?.label === label) last.items.push(item);
    else groups.push({ label, items: [item] });
  }

  return (
    <nav aria-label={m.chat_conversations()} className="flex flex-col gap-3 p-3">
      <Button
        className="w-full justify-start gap-2"
        onClick={() => {
          onOpen(undefined);
        }}
      >
        <Plus className="size-4" aria-hidden="true" />
        {m.chat_new()}
      </Button>
      <label className="flex items-center gap-2 rounded-lg border bg-card px-2.5 py-1.5 text-sm">
        <Search className="size-4 text-muted-foreground" aria-hidden="true" />
        <span className="sr-only">{m.chat_search()}</span>
        <input
          type="search"
          value={filter}
          placeholder={m.chat_search()}
          onChange={(event) => {
            setFilter(event.target.value);
          }}
          className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-muted-foreground"
        />
      </label>
      <h2 className="sr-only">{m.chat_conversations()}</h2>
      {items?.length === 0 && <p className="px-2 text-sm text-muted-foreground">{m.chat_none()}</p>}
      {groups.map((group) => (
        <section key={group.label} className="flex flex-col gap-0.5">
          <h3 className="px-2 pb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">
            {group.label}
          </h3>
          <ul className="flex flex-col gap-0.5">
            {group.items.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  aria-current={item.id === selected ? "true" : undefined}
                  className={cn(
                    "w-full truncate rounded-lg px-2 py-1.5 text-left text-sm hover:bg-accent/60",
                    item.id === selected && "bg-accent font-medium text-accent-foreground",
                  )}
                  onClick={() => {
                    onOpen(item.id);
                  }}
                >
                  {item.title}
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </nav>
  );
}

function Composer({
  running,
  onAsk,
  onStop,
}: {
  running: boolean;
  onAsk: (question: string) => void;
  onStop: () => void;
}) {
  const [question, setQuestion] = useState("");

  // From the form, or from Enter in the box (Shift and Enter makes a new line).
  function submit(event: { preventDefault: () => void }) {
    event.preventDefault();
    const asked = question.trim();
    if (asked === "" || running) return;
    setQuestion("");
    onAsk(asked);
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-1.5">
      <div className="flex items-end gap-2 rounded-3xl border bg-card p-2 pl-4 shadow-sm transition-shadow focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/30">
        <Label htmlFor="question" className="sr-only">
          {m.chat_question_label()}
        </Label>
        <textarea
          id="question"
          value={question}
          maxLength={MAX_QUESTION}
          rows={2}
          placeholder={m.chat_placeholder()}
          onChange={(event) => {
            setQuestion(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) submit(event);
          }}
          className="max-h-48 min-h-11 flex-1 resize-none bg-transparent py-2 text-base outline-none placeholder:text-muted-foreground md:text-sm"
        />
        {running ? (
          <Button
            type="button"
            size="icon-lg"
            variant="outline"
            className="rounded-full"
            aria-label={m.chat_stop()}
            onClick={onStop}
          >
            <Square className="size-4 fill-current" aria-hidden="true" />
          </Button>
        ) : (
          <Button
            type="submit"
            size="icon-lg"
            className="rounded-full"
            aria-label={m.chat_ask()}
            disabled={question.trim() === ""}
          >
            <ArrowUp className="size-5" aria-hidden="true" />
          </Button>
        )}
      </div>
      <p className="px-4 text-xs text-muted-foreground">{m.chat_hint()}</p>
    </form>
  );
}

function ConversationTools({
  conversation,
  onDeleted,
}: {
  conversation: Conversation;
  onDeleted: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [title, setTitle] = useState(conversation.title);
  const { run, error, busy } = useAction();

  async function rename(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const ok = await run(
      () => chatApi.rename(conversation.id, title),
      [LIST_KEY, conversationKey(conversation.id)],
    );
    if (ok) setEditing(false);
  }

  async function remove() {
    if (await run(() => chatApi.remove(conversation.id), [LIST_KEY])) onDeleted();
  }

  return (
    <div className="flex flex-col gap-2">
      {editing ? (
        <form
          onSubmit={(event) => void rename(event)}
          className="flex flex-wrap items-end gap-2 rounded-xl border bg-card p-3"
        >
          <div className="flex min-w-60 flex-1 flex-col gap-1">
            <Label htmlFor="conversation-title">{m.chat_title_label()}</Label>
            <Input
              id="conversation-title"
              value={title}
              maxLength={200}
              onChange={(event) => {
                setTitle(event.target.value);
              }}
            />
          </div>
          <Button type="submit" disabled={busy || title.trim() === ""}>
            {m.chat_save()}
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              setEditing(false);
            }}
          >
            {m.common_cancel()}
          </Button>
        </form>
      ) : (
        <div className="flex flex-wrap items-center justify-end gap-1">
          {confirming ? (
            <>
              <span className="mr-1 text-sm">{m.chat_delete_confirm()}</span>
              <Button size="sm" variant="destructive" onClick={() => void remove()}>
                {m.common_remove()}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setConfirming(false);
                }}
              >
                {m.common_cancel()}
              </Button>
            </>
          ) : (
            <>
              <Button
                size="sm"
                variant="ghost"
                className="gap-1.5 text-muted-foreground"
                onClick={() => {
                  setTitle(conversation.title);
                  setEditing(true);
                }}
              >
                <Pencil className="size-3.5" aria-hidden="true" />
                {m.chat_rename()}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="gap-1.5 text-muted-foreground"
                onClick={() => {
                  setConfirming(true);
                }}
              >
                <Trash2 className="size-3.5" aria-hidden="true" />
                {m.chat_delete()}
              </Button>
            </>
          )}
        </div>
      )}
      <FormError message={error} />
    </div>
  );
}
