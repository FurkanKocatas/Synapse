// Typed calls for chat and conversations (see docs/design/answers.md).

import { apiRequest, apiStream } from "@/lib/api";

import { serverEvents } from "./sse";

export interface Source {
  number: number;
  document_id: string;
  title: string;
  version: number;
  ordinal: number;
  page_start: number;
  page_end: number;
  heading_path: string[];
  // Null when the user may no longer read the document.
  text: string | null;
}

export type AnswerStatus = "answered" | "not_found" | "insufficient" | "failed";
export type TurnStatus = AnswerStatus | "pending" | "cancelled";
export type Feedback = "helpful" | "wrong_source" | "incomplete" | "invented";
// What an answer rests on: the documents (with sources), what the documents are (``library``, a
// question about the collection itself), or nothing (a reply in conversation, or one from
// general knowledge to a question that is not about the organisation).
export type AnswerKind = "documents" | "conversation" | "general" | "library";
// The assistant over the documents, or a plain conversation with the chat model.
export type ChatMode = "corporate" | "classic";

/** Where each mode lives: the corporate chat on the home page, the classic one under /chat. */
export const CHAT_PATH: Record<ChatMode, "/" | "/chat"> = { corporate: "/", classic: "/chat" };

export function modeOf(pathname: string): ChatMode {
  return pathname === "/chat" || pathname.startsWith("/chat/") ? "classic" : "corporate";
}

/** The user's clock with its offset ("2026-10-02T13:10:00+03:00"), so the model knows the day. */
export function localNow(at: Date = new Date()): string {
  const pad = (n: number) => String(Math.floor(Math.abs(n))).padStart(2, "0");
  const offset = -at.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  return (
    `${String(at.getFullYear())}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}` +
    `T${pad(at.getHours())}:${pad(at.getMinutes())}:${pad(at.getSeconds())}` +
    `${sign}${pad(offset / 60)}:${pad(offset % 60)}`
  );
}

export interface FinalAnswer {
  status: AnswerStatus;
  text: string;
  citations: number[];
  error: string | null;
  // How many sentences were removed because they stated a number no source holds.
  stripped: number;
  kind: AnswerKind;
}

export interface StoredTurn {
  ordinal: number;
  question: string;
  status: TurnStatus;
  answer: string | null;
  sources: Source[];
  citations: number[];
  feedback: Feedback | null;
  created_at: string;
  kind: AnswerKind;
}

export interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
  mode: ChatMode;
}

export interface Conversation {
  id: string;
  title: string;
  turns: StoredTurn[];
  mode: ChatMode;
}

/** What the chat endpoint streams, in order (backend/src/synapse/api/chat_routes.py). */
export type ChatEvent =
  | { event: "turn"; data: { conversation_id: string; ordinal: number } }
  | { event: "rewritten"; data: { question: string } }
  // ranked false: the first stage's order, replaced when the reranker has answered.
  | { event: "sources"; data: { sources: Source[]; warnings: string[]; ranked: boolean } }
  | { event: "queued"; data: { position: number } }
  | { event: "generating"; data: Record<string, never> }
  | { event: "delta"; data: { text: string } }
  | { event: "retrying"; data: { unsupported: string[] } }
  | { event: "answer"; data: FinalAnswer }
  | { event: "error"; data: { error: string } };

// Query keys shared by the conversation list (in the navigation) and the chat page. The
// first is both modes' lists (to refresh them), the second one mode's.
export const CONVERSATIONS = ["chat", "conversations"];
export function conversationsKey(mode: ChatMode) {
  return [...CONVERSATIONS, mode];
}
export function conversationKey(id: string | undefined) {
  return ["chat", "conversation", id ?? "new"];
}

export const chatApi = {
  conversations: (mode: ChatMode) =>
    apiRequest<ConversationSummary[]>("GET", `/api/conversations?mode=${mode}`),
  conversation: (id: string) => apiRequest<Conversation>("GET", `/api/conversations/${id}`),
  rename: (id: string, title: string) =>
    apiRequest<undefined>("PATCH", `/api/conversations/${id}`, { title }),
  remove: (id: string) => apiRequest<undefined>("DELETE", `/api/conversations/${id}`),
  feedback: (id: string, ordinal: number, kind: Feedback | null) =>
    apiRequest<undefined>("PUT", `/api/conversations/${id}/turns/${String(ordinal)}/feedback`, {
      kind,
    }),
  /** The events of one question; aborting ``signal`` cancels the answer on the server too. */
  async *ask(
    question: string,
    conversationId: string | null,
    mode: ChatMode,
    signal: AbortSignal,
  ): AsyncGenerator<ChatEvent, void, undefined> {
    const body = await apiStream(
      "/api/chat",
      {
        question,
        mode,
        now: localNow(),
        ...(conversationId === null ? {} : { conversation_id: conversationId }),
      },
      signal,
    );
    for await (const event of serverEvents(body)) yield event as ChatEvent;
  },
};

// The same expression the backend's verification reads (backend/src/synapse/chat/verification.py).
const CITATION = /\[(\d+(?:\s*,\s*\d+)*)\]/g;

export type AnswerPart = { text: string } | { citations: number[] };

/** The answer's text with its inline ``[n]`` markers taken out as citations. */
export function answerParts(text: string): AnswerPart[] {
  const parts: AnswerPart[] = [];
  let last = 0;
  for (const match of text.matchAll(CITATION)) {
    if (match.index > last) parts.push({ text: text.slice(last, match.index) });
    const numbers = match[1] ?? "";
    parts.push({ citations: numbers.split(",").map((n) => Number(n.trim())) });
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last) });
  return parts;
}

/** The answer as plain text, without its ``[n]`` markers (for copying). */
export function plainAnswer(text: string): string {
  return answerParts(text)
    .map((part) => ("text" in part ? part.text : ""))
    .join("")
    .replace(/ +([.,;:!?])/g, "$1")
    .replace(/ {2,}/g, " ")
    .trim();
}

/** Where ``passage`` (a chunk) stands in ``page``: [start, end) ranges, whitespace aside.
 * Chunks are cleaned text and may differ from the page in spacing or a joined hyphen, so each
 * of the passage's lines is looked for on its own and the ranges found are merged. */
export function passageRanges(page: string, passage: string): [number, number][] {
  const { flat, positions } = collapse(page);
  const ranges: [number, number][] = [];
  for (const line of passage.split(/\n+/)) {
    const wanted = line.split(/\s+/).filter(Boolean).join(" ");
    if (wanted.length < MIN_MATCH) continue;
    const at = flat.indexOf(wanted);
    if (at === -1) continue;
    const first = positions[at];
    const last = positions[at + wanted.length - 1];
    if (first !== undefined && last !== undefined) ranges.push([first, last + 1]);
  }
  ranges.sort((a, b) => a[0] - b[0]);
  const merged: [number, number][] = [];
  for (const range of ranges) {
    const previous = merged.at(-1);
    if (previous !== undefined && range[0] <= previous[1] + 1) {
      previous[1] = Math.max(previous[1], range[1]);
    } else merged.push([range[0], range[1]]);
  }
  return merged;
}

// Shorter lines (a lone number, a heading word) would mark every place they happen to occur.
const MIN_MATCH = 12;

/** ``text`` with each run of white space as one space, and where each kept character was. */
function collapse(text: string): { flat: string; positions: number[] } {
  let flat = "";
  const positions: number[] = [];
  let space = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text.charAt(i);
    if (/\s/.test(ch)) {
      space = flat.length > 0;
      continue;
    }
    if (space) {
      flat += " ";
      positions.push(i - 1);
      space = false;
    }
    flat += ch;
    positions.push(i);
  }
  return { flat, positions };
}
