import {
  ArchiveIcon,
  ArrowRightIcon,
  CoinsIcon,
  GavelIcon,
  type Icon,
} from "@phosphor-icons/react";
import { useQuery, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { useLocation, useNavigate, useSearch } from "@tanstack/react-router";
import { AnimatePresence } from "motion/react";
import { useEffect, useEffectEvent, useRef, useState } from "react";

import { Page } from "@/components/AppShell";
import { BlurText } from "@/components/reactbits/BlurText";
import { sessionQuery } from "@/features/auth/session";
import { m } from "@/paraglide/messages.js";

import { chatApi, CONVERSATIONS, conversationKey, type Source } from "./chatApi";
import { Composer } from "./Composer";
import { ConversationActions } from "./ConversationActions";
import { DocumentViewer } from "./DocumentViewer";
import { fromLive, fromStored, TurnView } from "./TurnView";
import { isRunning, useLiveTurn } from "./useLiveTurn";

const EXAMPLES: [() => string, Icon][] = [
  [m.chat_example_budget, CoinsIcon],
  [m.chat_example_council, GavelIcon],
  [m.chat_example_retention, ArchiveIcon],
];

// Pixels from the end within which the reader counts as following the answer.
const PINNED_WITHIN = 80;

/** "Good morning, Ayşe" and the like (the first name only), by the hour on the user's clock. */
export function greeting(displayName: string, hour: number): string {
  const name = displayName.trim().split(/\s+/)[0] ?? "";
  if (hour < 5 || hour >= 18) return m.home_greeting_evening({ name });
  if (hour < 11) return m.home_greeting_morning({ name });
  return m.home_greeting_day({ name });
}

/** The home page: one box to ask in, and the conversation so far. Past conversations are in
 * the navigation; a cited page opens beside the answers. */
export function ChatPage() {
  const { data: session } = useSuspenseQuery(sessionQuery);
  const { c: conversationId } = useSearch({ from: "/app/" });
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
      if (id !== conversationId) void navigate({ to: "/", search: { c: id }, replace: true });
    },
    onDone: async (id) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: CONVERSATIONS }),
        id === null ? null : queryClient.invalidateQueries({ queryKey: conversationKey(id) }),
      ]);
    },
  });
  const [viewing, setViewing] = useState<Source | null>(null);
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
      : m.chat_new();

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
          name={session?.user?.display_name ?? ""}
          running={running}
          focusKey={fresh}
          onAsk={ask}
          onStop={live.stop}
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
                    turn={fromStored(turn)}
                    onOpen={setViewing}
                    feedbackFor={{ conversationId: conversation.data.id, ordinal: turn.ordinal }}
                  />
                ))}
              {live.turn !== null && <TurnView turn={fromLive(live.turn)} onOpen={setViewing} />}
            </div>
          </div>
          <div className="relative shrink-0 px-3 pb-3 sm:px-8">
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 -top-8 h-8 bg-linear-to-b from-transparent to-background"
            />
            <Composer running={running} focusKey={conversationId} onAsk={ask} onStop={live.stop} />
          </div>
        </>
      )}
    </Page>
  );
}

function Welcome({
  name,
  running,
  focusKey,
  onAsk,
  onStop,
}: {
  name: string;
  running: boolean;
  focusKey: unknown;
  onAsk: (question: string) => void;
  onStop: () => void;
}) {
  // The hour is read once, when the page opens; the greeting does not change under the user.
  const [hour] = useState(() => new Date().getHours());
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 sm:px-8">
      <div className="mx-auto my-auto w-full max-w-[44rem] py-10 pb-[12vh]">
        <h2 className="text-[26px] leading-tight font-medium tracking-tight">
          <BlurText text={greeting(name, hour)} />
        </h2>
        <p className="mt-1.5 text-[15px] text-subtle-foreground">{m.home_next()}</p>
        <div className="mt-6">
          <Composer running={running} focusKey={focusKey} onAsk={onAsk} onStop={onStop} />
        </div>
        <section className="mt-6">
          <h3 className="px-0.5 pb-1 text-xs font-medium text-muted-foreground">
            {m.chat_examples()}
          </h3>
          <ul>
            {EXAMPLES.map(([example, IconFor]) => (
              <li key={example()} className="border-b last:border-b-0">
                <button
                  type="button"
                  onClick={() => {
                    onAsk(example());
                  }}
                  className="group flex w-full items-center gap-3 px-0.5 py-2.5 text-left text-sm text-subtle-foreground transition-colors hover:text-foreground"
                >
                  <IconFor
                    className="size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-secondary-foreground"
                    aria-hidden="true"
                  />
                  <span className="flex-1">{example()}</span>
                  <ArrowRightIcon
                    className="size-4 shrink-0 -translate-x-1 opacity-0 transition-[opacity,translate] group-hover:translate-x-0 group-hover:opacity-100"
                    aria-hidden="true"
                  />
                </button>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
