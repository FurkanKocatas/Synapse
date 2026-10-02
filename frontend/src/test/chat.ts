// What the chat's tests share: a signed-in user, a source and its page, a stored turn,
// server-sent events, and the fake API that answers the session.

import type { Source, StoredTurn } from "@/features/chat/chatApi";
import { getLocale } from "@/paraglide/runtime.js";
import { fakeApi, type Call } from "@/test/fakeApi";

export const user = {
  id: "u1",
  email: "editor@example.org",
  display_name: "Editor",
  role: "editor",
  locale: getLocale(),
};

export const source: Source = {
  number: 1,
  document_id: "d1",
  title: "Meclis Kararı",
  version: 1,
  ordinal: 0,
  page_start: 2,
  page_end: 2,
  heading_path: [],
  text: "Belediye meclisi 7 üyeden oluşur.",
};

export const page = {
  document_id: "d1",
  title: "Meclis Kararı",
  version: 1,
  number: 2,
  pages: 3,
  kind: "page",
  label: null,
  text: "Giriş.\nBelediye meclisi\n7 üyeden oluşur.\nSon.",
  text_source: "ocr",
  media_type: "application/pdf",
  chunks: [{ ordinal: 0, text: source.text, page_start: 2, page_end: 2 }],
};

export const answered: StoredTurn = {
  ordinal: 1,
  question: "Meclis kaç üyeli?",
  status: "answered",
  answer: "Meclis 7 üyeden oluşur. [1]",
  sources: [source],
  citations: [1],
  feedback: null,
  created_at: "2026-10-01T09:00:00Z",
  kind: "documents",
};

export function sse(events: [string, unknown][]): string {
  return events.map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join("");
}

export function api(
  handler: (call: Call) => { status: number; body?: unknown; text?: string } | undefined,
) {
  return fakeApi((call) => {
    if (call.path === "/api/auth/session") {
      return { status: 200, body: { auth_level: "full", csrf_token: "c", user } };
    }
    return handler(call) ?? { status: 200, body: [] };
  });
}
