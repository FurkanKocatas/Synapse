import { useState } from "react";

import { FormError } from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";

import {
  answerParts,
  chatApi,
  type Feedback,
  type Source,
  type StoredTurn,
  type TurnStatus,
} from "./chatApi";
import { isRunning, type LiveTurn } from "./useLiveTurn";

/** A turn as the page shows it, whether it is being answered or was stored. */
export interface ShownTurn {
  question: string;
  rewritten: string | null;
  sources: Source[] | null;
  warnings: string[];
  status: TurnStatus | null;
  text: string;
  citations: number[];
  stripped: number;
  feedback: Feedback | null;
  progress: string | null;
  error: string | null;
}

export function fromStored(turn: StoredTurn): ShownTurn {
  return {
    question: turn.question,
    rewritten: null,
    sources: turn.sources,
    warnings: [],
    status: turn.status,
    text: turn.answer ?? "",
    citations: turn.citations,
    stripped: 0,
    feedback: turn.feedback,
    progress: null,
    error: null,
  };
}

export function fromLive(turn: LiveTurn): ShownTurn {
  let progress: string | null = null;
  if (isRunning(turn)) {
    if (turn.sources === null) progress = m.chat_searching();
    else if (turn.queuePosition !== null)
      progress = m.chat_queued({ position: String(turn.queuePosition) });
    else if (turn.retrying) progress = m.chat_retrying();
    else progress = m.chat_generating();
  }
  return {
    question: turn.question,
    rewritten: turn.rewritten,
    sources: turn.sources,
    warnings: turn.warnings,
    status: turn.cancelled ? "cancelled" : (turn.answer?.status ?? null),
    text: turn.answer?.text ?? turn.text,
    citations: turn.answer?.citations ?? [],
    stripped: turn.answer?.stripped ?? 0,
    feedback: null,
    progress,
    error: turn.error,
  };
}

const WARNINGS: Record<string, () => string> = {
  embedding_unavailable: m.chat_warning_embedding_unavailable,
  reranking_unavailable: m.chat_warning_reranking_unavailable,
};

export function TurnView({
  turn,
  onOpen,
  feedbackFor,
}: {
  turn: ShownTurn;
  onOpen: (source: Source) => void;
  // Where to store feedback; absent while the turn is being answered.
  feedbackFor?: { conversationId: string; ordinal: number };
}) {
  const answered = turn.status === "answered";
  return (
    <article className="flex flex-col gap-3 border-b pb-6">
      <p className="self-end rounded-lg bg-muted px-3 py-2 whitespace-pre-wrap">{turn.question}</p>
      {turn.rewritten !== null && (
        <p className="text-xs text-muted-foreground">
          {m.chat_rewritten({ question: turn.rewritten })}
        </p>
      )}
      {turn.warnings.map((warning) => (
        <p key={warning} className="text-xs text-muted-foreground">
          {(WARNINGS[warning] ?? m.error_unexpected)()}
        </p>
      ))}
      {turn.sources !== null && turn.sources.length > 0 && (
        <SourceList
          sources={turn.sources}
          title={answered || turn.status === null ? m.chat_sources() : m.chat_related()}
          onOpen={onOpen}
        />
      )}
      <div aria-live="polite" className="flex flex-col gap-2">
        {turn.text !== "" && (answered || turn.status === null) && (
          <AnswerText text={turn.text} sources={turn.sources ?? []} onOpen={onOpen} />
        )}
        {answered && (
          <CitedSources citations={turn.citations} sources={turn.sources ?? []} onOpen={onOpen} />
        )}
        {turn.stripped > 0 && <p className="text-xs text-muted-foreground">{m.chat_stripped()}</p>}
        {turn.progress !== null && (
          <p className="animate-pulse text-sm text-muted-foreground">{turn.progress}</p>
        )}
        <StatusLine status={turn.status} />
        <FormError message={turn.error} />
      </div>
      {answered && feedbackFor !== undefined && (
        <FeedbackBar initial={turn.feedback} {...feedbackFor} />
      )}
    </article>
  );
}

const STATUS_TEXT: Partial<Record<TurnStatus, () => string>> = {
  not_found: m.chat_not_found,
  insufficient: m.chat_insufficient,
  failed: m.chat_failed,
  cancelled: m.chat_cancelled,
  pending: m.chat_pending,
};

function StatusLine({ status }: { status: TurnStatus | null }) {
  const text = status === null ? undefined : STATUS_TEXT[status];
  return text === undefined ? null : <p className="text-sm">{text()}</p>;
}

function pages(source: Source): string {
  return source.page_start === source.page_end
    ? m.chat_page({ page: String(source.page_start) })
    : m.chat_pages({ start: String(source.page_start), end: String(source.page_end) });
}

function SourceList({
  sources,
  title,
  onOpen,
}: {
  sources: Source[];
  title: string;
  onOpen: (source: Source) => void;
}) {
  return (
    <section aria-label={title} className="flex flex-col gap-2">
      <h3 className="text-sm font-medium">{title}</h3>
      <ol className="grid gap-2 sm:grid-cols-2">
        {sources.map((source) => (
          <li key={source.number}>
            <button
              type="button"
              disabled={source.text === null}
              onClick={() => {
                onOpen(source);
              }}
              className="flex w-full flex-col gap-1 rounded-lg border p-2 text-left text-sm hover:bg-muted disabled:opacity-60"
            >
              <span className="font-medium">
                [{source.number}] {source.text === null ? m.chat_source_gone() : source.title}
              </span>
              <span className="text-xs text-muted-foreground">{pages(source)}</span>
              {source.text !== null && <span className="line-clamp-3 text-xs">{source.text}</span>}
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

function CitationButton({
  number,
  sources,
  onOpen,
}: {
  number: number;
  sources: Source[];
  onOpen: (source: Source) => void;
}) {
  const source = sources.find((s) => s.number === number);
  if (source === undefined) return null;
  return (
    <button
      type="button"
      aria-label={m.chat_citation_label({ number: String(number) })}
      disabled={source.text === null}
      onClick={() => {
        onOpen(source);
      }}
      className="mx-0.5 rounded bg-primary/10 px-1 align-super text-xs font-medium text-primary hover:bg-primary/20 disabled:opacity-60"
    >
      {number}
    </button>
  );
}

function AnswerText({
  text,
  sources,
  onOpen,
}: {
  text: string;
  sources: Source[];
  onOpen: (source: Source) => void;
}) {
  return (
    <p className="leading-relaxed whitespace-pre-wrap">
      {answerParts(text).map((part, index) =>
        "text" in part ? (
          <span key={index}>{part.text}</span>
        ) : (
          <span key={index}>
            {part.citations.map((number) => (
              <CitationButton key={number} number={number} sources={sources} onOpen={onOpen} />
            ))}
          </span>
        ),
      )}
    </p>
  );
}

function CitedSources({
  citations,
  sources,
  onOpen,
}: {
  citations: number[];
  sources: Source[];
  onOpen: (source: Source) => void;
}) {
  if (citations.length === 0) return null;
  return (
    <p className="text-xs text-muted-foreground">
      {m.chat_based_on()}:{" "}
      {citations.map((number) => (
        <CitationButton key={number} number={number} sources={sources} onOpen={onOpen} />
      ))}
    </p>
  );
}

const FEEDBACK: [Feedback, () => string][] = [
  ["helpful", m.chat_feedback_helpful],
  ["wrong_source", m.chat_feedback_wrong_source],
  ["incomplete", m.chat_feedback_incomplete],
  ["invented", m.chat_feedback_invented],
];

function FeedbackBar({
  initial,
  conversationId,
  ordinal,
}: {
  initial: Feedback | null;
  conversationId: string;
  ordinal: number;
}) {
  const [chosen, setChosen] = useState<Feedback | null>(initial);
  const [error, setError] = useState<string | null>(null);

  async function choose(kind: Feedback) {
    const next = chosen === kind ? null : kind;
    setError(null);
    try {
      await chatApi.feedback(conversationId, ordinal, next);
      setChosen(next);
    } catch {
      setError(m.error_unexpected());
    }
  }

  return (
    <div role="group" aria-label={m.chat_feedback_label()} className="flex flex-wrap gap-2">
      {FEEDBACK.map(([kind, label]) => (
        <Button
          key={kind}
          size="xs"
          variant="outline"
          aria-pressed={chosen === kind}
          className={cn(chosen === kind && "bg-muted font-semibold")}
          onClick={() => void choose(kind)}
        >
          {label()}
        </Button>
      ))}
      <FormError message={error} />
    </div>
  );
}
