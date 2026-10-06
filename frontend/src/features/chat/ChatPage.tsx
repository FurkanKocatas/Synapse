import { useQuery, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { useLocation, useNavigate, useSearch } from "@tanstack/react-router";
import { AnimatePresence } from "motion/react";
import { useEffect, useEffectEvent, useRef, useState } from "react";

import { Page } from "@/components/AppShell";
import { sessionQuery } from "@/features/auth/session";
import { m } from "@/paraglide/messages.js";

import {
  CHAT_PATH,
  chatApi,
  CONVERSATIONS,
  conversationKey,
  type ChatMode,
  type Source,
} from "./chatApi";
import { Composer } from "./Composer";
import { EVERYTHING, type ChatScope } from "./scope";
import { ConversationActions } from "./ConversationActions";
import { DocumentViewer } from "./DocumentViewer";
import { fromLive, fromStored, TurnView } from "./TurnView";
import { isRunning, useLiveTurn } from "./useLiveTurn";
import { Welcome } from "./Welcome";

export { greeting } from "./Welcome";

// Pixels from the end within which the reader counts as following the answer.
const PINNED_WITHIN = 80;

/** The classic chat, under /chat: the same page, answering without the documents. */
export function ClassicChatPage() {
  return <ChatPage mode="classic" />;
}

/** A chat: one box to ask in, and the conversation so far. The corporate chat (the home page)
 * answers from the documents, the classic one is a plain conversation with the model. Past
 * conversations are in the navigation; a cited page opens beside the answers. */
export function ChatPage({ mode = "corporate" }: { mode?: ChatMode }) {
  const { data: session } = useSuspenseQuery(sessionQuery);
  const { c: conversationId } = useSearch({ strict: false });
  const fresh = useLocation({ select: (location) => location.state.fresh });
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const conversation = useQuery({
    queryKey: conversationKey(conversationId),
    queryFn: () => chatApi.conversation(conversationId ?? ""),
    enabled: conversationId !== undefined,
  });
  const live = useLiveTurn({
    onTurn: (id) => {
      if (id !== conversationId) {
        void navigate({ to: CHAT_PATH[mode], search: { c: id }, replace: true });
      }
    },
    onDone: async (id) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: CONVERSATIONS }),
        id === null ? null : queryClient.invalidateQueries({ queryKey: conversationKey(id) }),
      ]);
    },
  });
  const [viewing, setViewing] = useState<Source | null>(null);
  // Where the next question is searched, when chosen on this page; otherwise the
  // conversation's own scope, everything for a new one.
  const [chosenScope, setChosenScope] = useState<ChatScope | null>(null);
  const scope = chosenScope ?? conversation.data?.scope ?? EVERYTHING;
  const running = isRunning(live.turn);
  const scroller = useRef<HTMLDivElement>(null);
  // Whether the reader is at the end of the conversation, so a growing answer keeps in view.
  const pinned = useRef(true);

  // Another conversation, or a new one, was opened from the navigation: what was on screen
  // goes (a cited page is closed while rendering; the answer being written is stopped below).
  const place = `${conversationId ?? ""}:${String(fresh ?? "")}`;
  const [shownPlace, setShownPlace] = useState(place);
  if (shownPlace !== place) {
    setShownPlace(place);
    setViewing(null);
    // A conversation opened from the navigation keeps its own scope; a new one starts with
    // everything. Asking in a new conversation only gives it an id: the choice stays.
    const asked = live.turn !== null && live.turn.conversationId === (conversationId ?? null);
    if (!asked) setChosenScope(null);
  }
  const leave = useEffectEvent((startOver: boolean) => {
    const turn = live.turn;
    if (turn === null) return;
    const elsewhere = turn.conversationId !== null && turn.conversationId !== conversationId;
    if (startOver || elsewhere) live.clear();
  });
  useEffect(() => {
    leave(false);
  }, [conversationId]);
  useEffect(() => {
    if (fresh !== undefined) leave(true);
  }, [fresh]);

  useEffect(() => {
    const element = scroller.current;
    if (element !== null && pinned.current) element.scrollTop = element.scrollHeight;
  }, [live.turn]);

  function ask(question: string) {
    pinned.current = true;
    void live.ask(question, conversationId ?? null, mode, scope, chosenScope !== null);
  }

  const stored = conversation.data?.turns ?? [];
  // While a turn is live, its stored row (pending, then final) is not shown twice.
  const shownStored =
    live.turn === null ? stored : stored.filter((t) => t.ordinal !== live.turn?.ordinal);
  const empty = conversationId === undefined && live.turn === null;
  const title =
    conversationId !== undefined && conversation.data !== undefined
      ? conversation.data.title
      : mode === "classic"
        ? m.nav_chat_classic()
        : m.nav_chat_corporate();

  return (
    <Page
      title={title}
      wide
      actions={
        conversation.data !== undefined &&
        conversationId !== undefined && (
          <ConversationActions conversation={conversation.data} label={m.chat_actions()} />
        )
      }
      panel={
        <AnimatePresence>
          {viewing !== null && (
            <DocumentViewer
              key={`${viewing.document_id}:${String(viewing.ordinal)}`}
              source={viewing}
              onClose={() => {
                setViewing(null);
              }}
            />
          )}
        </AnimatePresence>
      }
    >
      {empty ? (
        <Welcome
          mode={mode}
          name={session?.user?.display_name ?? ""}
          running={running}
          focusKey={fresh}
          onAsk={ask}
          onStop={live.stop}
          scope={scope}
          onScope={setChosenScope}
        />
      ) : (
        <>
          <div
            ref={scroller}
            onScroll={(event) => {
              const element = event.currentTarget;
              pinned.current =
                element.scrollHeight - element.scrollTop - element.clientHeight < PINNED_WITHIN;
            }}
            className="min-h-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]"
          >
            <div className="mx-auto w-full max-w-3xl px-4 pb-6 sm:px-8">
              {conversation.data !== undefined &&
                shownStored.map((turn) => (
                  <TurnView
                    key={turn.ordinal}
                    mode={mode}
                    turn={fromStored(turn)}
                    onOpen={setViewing}
                    feedbackFor={{ conversationId: conversation.data.id, ordinal: turn.ordinal }}
                  />
                ))}
              {live.turn !== null && (
                <TurnView mode={mode} turn={fromLive(live.turn, mode)} onOpen={setViewing} />
              )}
            </div>
          </div>
          <div className="relative shrink-0 px-3 pb-3 sm:px-8">
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 -top-8 h-8 bg-linear-to-b from-transparent to-background"
            />
            <Composer
              mode={mode}
              running={running}
              focusKey={conversationId}
              onAsk={ask}
              onStop={live.stop}
              scope={scope}
              onScope={setChosenScope}
            />
          </div>
        </>
      )}
    </Page>
  );
}
