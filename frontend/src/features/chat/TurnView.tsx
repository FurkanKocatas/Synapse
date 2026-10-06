import {
  BooksIcon,
  CheckCircleIcon,
  CircleIcon,
  CircleNotchIcon,
  FunnelSimpleIcon,
  InfoIcon,
  MagnifyingGlassIcon,
  StopCircleIcon,
  WarningIcon,
  WarningCircleIcon,
  type Icon,
} from "@phosphor-icons/react";
import { useState } from "react";

import { FormError } from "@/components/AuthLayout";
import { LogoMark } from "@/components/Logo";
import { ShinyText } from "@/components/reactbits/ShinyText";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";

import type { AnswerKind, ChatMode, Feedback, Source, StoredTurn, TurnStatus } from "./chatApi";
import { AnswerActions } from "./Feedback";
import { Markdown } from "./Markdown";
import { isEverything, scopeLabel, useScopeNames, type ChatScope } from "./scope";
import { AnswerText, SourceRow } from "./Sources";
import { isRunning, type LiveTurn } from "./useLiveTurn";

// Where a turn being answered is: searching, ranking what was found, or writing.
type Stage =
  | { step: "search" }
  | { step: "rank" }
  // ``alone``: nothing was searched (a greeting), so writing is the only step.
  | { step: "write"; text: string; alone?: boolean };

/** A turn as the page shows it, whether it is being answered or was stored. */
export interface ShownTurn {
  question: string;
  rewritten: string | null;
  sources: Source[] | null;
  ranked: boolean;
  warnings: string[];
  status: TurnStatus | null;
  text: string;
  citations: number[];
  stripped: number;
  feedback: Feedback | null;
  stage: Stage | null;
  error: string | null;
  live: boolean;
  kind: AnswerKind;
  // Where it searched; null: everything the user could read.
  scope: ChatScope | null;
}

export function fromStored(turn: StoredTurn): ShownTurn {
  return {
    question: turn.question,
    rewritten: null,
    sources: turn.sources,
    ranked: true,
    warnings: [],
    status: turn.status,
    text: turn.answer ?? "",
    citations: turn.citations,
    stripped: 0,
    feedback: turn.feedback,
    stage: null,
    error: null,
    live: false,
    kind: turn.kind,
    scope: turn.scope ?? null,
  };
}

function stageOf(turn: LiveTurn, mode: ChatMode): Stage | null {
  if (!isRunning(turn)) return null;
  if (mode === "classic") {
    const text =
      turn.queuePosition === null
        ? m.chat_generating()
        : m.chat_queued({ position: String(turn.queuePosition) });
    return { step: "write", text, alone: true };
  }
  if (turn.sources === null) {
    return turn.generating
      ? { step: "write", text: m.chat_generating(), alone: true }
      : { step: "search" };
  }
  if (!turn.ranked) return { step: "rank" };
  if (turn.queuePosition !== null) {
    return { step: "write", text: m.chat_queued({ position: String(turn.queuePosition) }) };
  }
  return { step: "write", text: turn.retrying ? m.chat_retrying() : m.chat_generating() };
}

export function fromLive(turn: LiveTurn, mode: ChatMode = "corporate"): ShownTurn {
  return {
    question: turn.question,
    rewritten: turn.rewritten,
    sources: turn.sources,
    ranked: turn.ranked,
    warnings: turn.warnings,
    status: turn.cancelled ? "cancelled" : (turn.answer?.status ?? null),
    text: turn.answer?.text ?? turn.text,
    citations: turn.answer?.citations ?? [],
    stripped: turn.answer?.stripped ?? 0,
    feedback: null,
    stage: stageOf(turn, mode),
    error: turn.error,
    live: true,
    kind: turn.answer?.kind ?? "documents",
    scope: mode === "classic" ? null : turn.scope,
  };
}

/** Where a question was searched, when it was not everything the user could read. */
function Searched({ scope }: { scope: ChatScope }) {
  const { names, titles } = useScopeNames();
  return (
    <p className="mt-1.5 flex items-center gap-1.5 text-[13px] text-muted-foreground">
      <FunnelSimpleIcon className="size-3.5 shrink-0" aria-hidden="true" />
      {m.chat_scope_searched({ scope: scopeLabel(scope, names, titles) })}
    </p>
  );
}

const WARNINGS: Record<string, () => string> = {
  embedding_unavailable: m.chat_warning_embedding_unavailable,
  reranking_unavailable: m.chat_warning_reranking_unavailable,
};

/** One question and its answer: the question as a heading, the steps while it is answered,
 * the sources, the answer with its citations, and what can be done with it. */
export function TurnView({
  mode = "corporate",
  turn,
  onOpen,
  feedbackFor,
}: {
  mode?: ChatMode;
  turn: ShownTurn;
  onOpen: (source: Source) => void;
  // Where to store feedback; absent while the turn is being answered.
  feedbackFor?: { conversationId: string; ordinal: number };
}) {
  const [linked, setLinked] = useState<number | null>(null);
  const answered = turn.status === "answered";
  const writing = answered || turn.status === null;
  // A reply in conversation or from general knowledge used none of what the search found.
  const grounded = turn.kind === "documents";

  return (
    <article className="py-7">
      <h2
        className={cn(
          "text-[22px] leading-snug font-semibold tracking-tight text-pretty",
          turn.live && "animate-rise",
        )}
      >
        {turn.question}
      </h2>
      {!isEverything(turn.scope) && turn.scope !== null && <Searched scope={turn.scope} />}
      {turn.rewritten !== null && (
        <p className="mt-1.5 flex animate-arrive items-center gap-1.5 text-[13px] text-muted-foreground">
          <MagnifyingGlassIcon className="size-3.5 shrink-0" aria-hidden="true" />
          {m.chat_rewritten({ question: turn.rewritten })}
        </p>
      )}
      {turn.stage !== null ? (
        <Steps stage={turn.stage} found={turn.sources?.length ?? 0} />
      ) : (
        answered &&
        grounded &&
        turn.sources !== null && (
          <p className="mt-3.5 flex items-center gap-1.5 text-[13px] text-muted-foreground">
            <BooksIcon className="size-4" aria-hidden="true" />
            {m.chat_found({
              found: String(turn.sources.length),
              cited: String(new Set(turn.citations).size),
            })}
          </p>
        )
      )}
      {turn.warnings.map((warning) => (
        <p key={warning} className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
          <WarningIcon className="size-3.5 shrink-0" aria-hidden="true" />
          {(WARNINGS[warning] ?? m.error_unexpected)()}
        </p>
      ))}
      {grounded && turn.sources !== null && turn.sources.length > 0 && (
        <SourceRow
          sources={turn.sources}
          title={writing ? m.chat_sources() : m.chat_related()}
          showTitle={!writing}
          ranked={turn.ranked}
          live={turn.live}
          linked={linked}
          onOpen={onOpen}
        />
      )}
      {(turn.text !== "" || turn.status !== null || turn.error !== null) && (
        // The answer, on a card of its own under the question and its sources.
        <div
          className={cn(
            "mt-4 rounded-2xl border bg-card px-5 pt-4 pb-3 shadow-raised",
            turn.live && "animate-rise",
          )}
        >
          <p className="mb-2 flex items-center gap-2 text-xs font-semibold tracking-wide text-muted-foreground">
            <LogoMark className="size-5" />
            {m.chat_answer()}
          </p>
          {turn.kind === "general" && mode === "corporate" && (
            <p className="mb-3 flex items-center gap-2 rounded-lg bg-muted px-3 py-2 text-[13px] text-subtle-foreground">
              <InfoIcon className="size-4 shrink-0" aria-hidden="true" />
              {m.chat_general_note()}
            </p>
          )}
          <div aria-live="polite" className="[&>*:first-child]:mt-0">
            {turn.text !== "" && writing && !grounded && <Markdown text={turn.text} />}
            {turn.text !== "" && writing && grounded && (
              <AnswerText
                text={turn.text}
                sources={turn.sources ?? []}
                live={turn.live}
                onOpen={onOpen}
                onLook={setLinked}
              />
            )}
            {turn.stripped > 0 && <Note icon={InfoIcon} text={m.chat_stripped()} />}
            <StatusNote status={turn.status} />
            <FormError message={turn.error} />
          </div>
          {answered && feedbackFor !== undefined && (
            <div className="-mx-2 mt-3 border-t pt-2">
              <AnswerActions text={turn.text} initial={turn.feedback} {...feedbackFor} />
            </div>
          )}
        </div>
      )}
    </article>
  );
}

const STEPS = ["search", "rank", "write"] as const;

/** The three steps of an answer, the current one shimmering. */
function Steps({ stage, found }: { stage: Stage; found: number }) {
  const at = STEPS.indexOf(stage.step);
  const shown = stage.step === "write" && stage.alone === true ? (["write"] as const) : STEPS;
  const labels = {
    search: at > 0 ? m.chat_step_found({ count: String(found) }) : m.chat_searching(),
    rank: at > 1 ? m.chat_step_ranked() : m.chat_ranking(),
    write: stage.step === "write" ? stage.text : m.chat_generating(),
  };
  return (
    <ol className="mt-3.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px]">
      {shown.map((step) => {
        const index = STEPS.indexOf(step);
        const state = index < at ? "done" : index === at ? "active" : "todo";
        return (
          <li
            key={step}
            className={cn(
              "flex items-center gap-1.5 transition-colors",
              state === "done" && "text-subtle-foreground",
              state === "active" && "text-foreground",
              state === "todo" && "text-muted-foreground/70",
            )}
          >
            {state === "done" && (
              <CheckCircleIcon weight="fill" className="size-4 text-success" aria-hidden="true" />
            )}
            {state === "active" && (
              <CircleNotchIcon
                className="size-4 animate-spin text-secondary-foreground"
                aria-hidden="true"
              />
            )}
            {state === "todo" && <CircleIcon className="size-4" aria-hidden="true" />}
            {state === "active" ? <ShinyText text={labels[step]} /> : labels[step]}
          </li>
        );
      })}
    </ol>
  );
}

const STATUS: Partial<Record<TurnStatus, [() => string, Icon]>> = {
  not_found: [m.chat_not_found, MagnifyingGlassIcon],
  insufficient: [m.chat_insufficient, InfoIcon],
  failed: [m.chat_failed, WarningCircleIcon],
  cancelled: [m.chat_cancelled, StopCircleIcon],
  pending: [m.chat_pending, InfoIcon],
};

function StatusNote({ status }: { status: TurnStatus | null }) {
  const found = status === null ? undefined : STATUS[status];
  if (found === undefined) return null;
  const [text, icon] = found;
  return <Note icon={icon} text={text()} />;
}

function Note({ icon: IconFor, text }: { icon: Icon; text: string }) {
  return (
    <p className="mt-4 flex animate-arrive items-start gap-2 rounded-lg bg-muted px-3 py-2.5 text-sm text-subtle-foreground">
      <IconFor className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      {text}
    </p>
  );
}
