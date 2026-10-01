import { useQuery, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { useState, type SubmitEvent } from "react";

import { AppShell } from "@/components/AppShell";
import { FormError } from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { sessionQuery } from "@/features/auth/session";
import { useAction } from "@/lib/useAction";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";

import { chatApi, type Conversation, type Source } from "./chatApi";
import { DocumentViewer } from "./DocumentViewer";
import { fromLive, fromStored, TurnView } from "./TurnView";
import { isRunning, useLiveTurn } from "./useLiveTurn";

const LIST_KEY = ["chat", "conversations"];
const MAX_QUESTION = 1000;

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

  const stored = conversation.data?.turns ?? [];
  // While a turn is live, its stored row (pending, then final) is not shown twice.
  const shownStored =
    live.turn === null ? stored : stored.filter((t) => t.ordinal !== live.turn?.ordinal);

  return (
    <AppShell>
      <div className="grid gap-4 md:grid-cols-[15rem_1fr]">
        <nav aria-label={m.chat_conversations()} className="flex flex-col gap-2">
          <Button
            variant="outline"
            onClick={() => {
              open(undefined);
            }}
          >
            {m.chat_new()}
          </Button>
          <h2 className="px-2 text-sm font-medium text-muted-foreground">
            {m.chat_conversations()}
          </h2>
          {conversations.data?.length === 0 && (
            <p className="px-2 text-sm text-muted-foreground">{m.chat_none()}</p>
          )}
          <ul className="flex flex-col">
            {conversations.data?.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  aria-current={item.id === conversationId ? "true" : undefined}
                  className={cn(
                    "w-full truncate rounded px-2 py-1 text-left text-sm hover:bg-muted",
                    item.id === conversationId && "bg-muted font-medium",
                  )}
                  onClick={() => {
                    open(item.id);
                  }}
                >
                  {item.title}
                </button>
              </li>
            ))}
          </ul>
        </nav>
        <section className="flex min-w-0 flex-col gap-6">
          {conversation.data !== undefined && conversationId !== undefined ? (
            <ConversationHeader
              conversation={conversation.data}
              onDeleted={() => {
                open(undefined);
              }}
            />
          ) : (
            stored.length === 0 &&
            live.turn === null && (
              <div>
                <h1 className="text-2xl font-semibold">
                  {m.home_welcome({ name: session?.user?.display_name ?? "" })}
                </h1>
                <p className="text-muted-foreground">{m.home_next()}</p>
              </div>
            )
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
          <Composer
            running={running}
            onAsk={(question) => void live.ask(question, conversationId ?? null)}
            onStop={live.stop}
          />
        </section>
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
    <form onSubmit={submit} className="sticky bottom-0 flex flex-col gap-2 bg-background py-2">
      <Label htmlFor="question">{m.chat_question_label()}</Label>
      <textarea
        id="question"
        value={question}
        maxLength={MAX_QUESTION}
        rows={2}
        onChange={(event) => {
          setQuestion(event.target.value);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) submit(event);
        }}
        className="w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-base outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:text-sm"
      />
      <div className="flex gap-2">
        {running ? (
          <Button type="button" variant="outline" onClick={onStop}>
            {m.chat_stop()}
          </Button>
        ) : (
          <Button type="submit" disabled={question.trim() === ""}>
            {m.chat_ask()}
          </Button>
        )}
      </div>
    </form>
  );
}

function ConversationHeader({
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
    <header className="flex flex-col gap-2">
      {editing ? (
        <form onSubmit={(event) => void rename(event)} className="flex flex-wrap items-end gap-2">
          <div className="flex flex-col gap-1">
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
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold">{conversation.title}</h1>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setTitle(conversation.title);
              setEditing(true);
            }}
          >
            {m.chat_rename()}
          </Button>
          {confirming ? (
            <>
              <span className="text-sm">{m.chat_delete_confirm()}</span>
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
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setConfirming(true);
              }}
            >
              {m.chat_delete()}
            </Button>
          )}
        </div>
      )}
      <FormError message={error} />
    </header>
  );
}
