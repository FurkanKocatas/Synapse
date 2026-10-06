// The question being answered right now, built up from the chat endpoint's events.

import { useRef, useState } from "react";

import { errorMessage } from "@/features/auth/errors";

import { chatApi, type ChatEvent, type ChatMode, type FinalAnswer, type Source } from "./chatApi";
import type { ChatScope } from "./scope";

export interface LiveTurn {
  question: string;
  conversationId: string | null;
  ordinal: number | null;
  rewritten: string | null;
  // Null until search has answered.
  sources: Source[] | null;
  warnings: string[];
  // False while the sources are in the first stage's order.
  ranked: boolean;
  queuePosition: number | null;
  generating: boolean;
  retrying: boolean;
  text: string;
  answer: FinalAnswer | null;
  // A sentence for the user when the request itself failed.
  error: string | null;
  cancelled: boolean;
  // Where it searches; null: everything the user may read.
  scope: ChatScope | null;
}

export function started(
  question: string,
  conversationId: string | null,
  scope: ChatScope | null = null,
): LiveTurn {
  return {
    question,
    conversationId,
    scope,
    ordinal: null,
    rewritten: null,
    sources: null,
    warnings: [],
    ranked: false,
    queuePosition: null,
    generating: false,
    retrying: false,
    text: "",
    answer: null,
    error: null,
    cancelled: false,
  };
}

/** The turn after ``event``. */
export function advance(turn: LiveTurn, event: ChatEvent): LiveTurn {
  switch (event.event) {
    case "turn":
      return { ...turn, conversationId: event.data.conversation_id, ordinal: event.data.ordinal };
    case "rewritten":
      return { ...turn, rewritten: event.data.question };
    case "sources":
      return {
        ...turn,
        sources: event.data.sources,
        warnings: event.data.warnings,
        ranked: event.data.ranked,
      };
    case "queued":
      return { ...turn, queuePosition: event.data.position };
    case "generating":
      // The answer starts (over): after a refusal the server replaces with a reply, for one.
      return { ...turn, queuePosition: null, generating: true, text: "" };
    case "delta":
      return { ...turn, text: turn.text + event.data.text };
    case "retrying":
      return { ...turn, text: "", retrying: true };
    case "answer":
      return { ...turn, generating: false, retrying: false, answer: event.data };
    case "error":
      return { ...turn, generating: false, error: errorMessage(null) };
  }
}

export function isRunning(turn: LiveTurn | null): boolean {
  return turn !== null && turn.answer === null && turn.error === null && !turn.cancelled;
}

/** Asks, follows the events, and stops on request. ``onTurn`` hears where the turn is stored
 * as soon as it is; ``onDone`` when the answer is complete (or the request ended). */
export function useLiveTurn(callbacks: {
  onTurn: (conversationId: string) => void;
  onDone: (conversationId: string | null) => Promise<void>;
}) {
  const [turn, setTurn] = useState<LiveTurn | null>(null);
  const controller = useRef<AbortController | null>(null);

  /** ``scope`` is where the question is searched; ``send`` whether to tell the server (a
   * choice made on this page), or let the conversation keep its own. */
  async function ask(
    question: string,
    conversationId: string | null,
    mode: ChatMode,
    scope: ChatScope | null = null,
    send = false,
  ) {
    const abort = new AbortController();
    controller.current = abort;
    let current = started(question, conversationId, scope);
    setTurn(current);
    const told = send && scope !== null ? scope : undefined;
    try {
      for await (const event of chatApi.ask(question, conversationId, mode, abort.signal, told)) {
        current = advance(current, event);
        setTurn(current);
        if (event.event === "turn") callbacks.onTurn(event.data.conversation_id);
      }
    } catch (failure) {
      current = abort.signal.aborted
        ? { ...current, cancelled: true, generating: false }
        : { ...current, generating: false, error: errorMessage(failure) };
      setTurn(current);
    } finally {
      controller.current = null;
    }
    await callbacks.onDone(current.conversationId);
    // The stored turn has replaced the live one; a failure stays shown until the next question.
    if (current.answer !== null) setTurn(null);
  }

  function stop() {
    controller.current?.abort();
  }

  function clear() {
    stop();
    setTurn(null);
  }

  return { turn, ask, stop, clear };
}
