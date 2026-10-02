import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "@/App";
import { rememberCsrfToken } from "@/lib/api";
import { greeting } from "@/features/chat/ChatPage";
import { m } from "@/paraglide/messages.js";
import { getLocale } from "@/paraglide/runtime.js";
import { fakeApi, type Call } from "@/test/fakeApi";

import { fileKind } from "@/lib/fileKind";

import { answerParts, passageRanges, plainAnswer, type Source, type StoredTurn } from "./chatApi";
import { markPassage } from "./PdfPage";
import { serverEvents } from "./sse";
import { advance, isRunning, started } from "./useLiveTurn";

const user = {
  id: "u1",
  email: "editor@example.org",
  display_name: "Editor",
  role: "editor",
  locale: getLocale(),
};

const source: Source = {
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

const page = {
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

const answered: StoredTurn = {
  ordinal: 1,
  question: "Meclis kaç üyeli?",
  status: "answered",
  answer: "Meclis 7 üyeden oluşur. [1]",
  sources: [source],
  citations: [1],
  feedback: null,
  created_at: "2026-10-01T09:00:00Z",
};

function sse(events: [string, unknown][]): string {
  return events.map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join("");
}

// PDF.js needs a canvas, which jsdom does not have; the page is drawn in the browser only.
vi.mock("./PdfPage", async (original) => ({
  ...(await original<typeof import("./PdfPage")>()),
  PdfPage: () => null,
}));

afterEach(() => {
  vi.unstubAllGlobals();
  rememberCsrfToken(null);
  window.history.replaceState(null, "", "/");
});

function api(
  handler: (call: Call) => { status: number; body?: unknown; text?: string } | undefined,
) {
  return fakeApi((call) => {
    if (call.path === "/api/auth/session") {
      return { status: 200, body: { auth_level: "full", csrf_token: "c", user } };
    }
    return handler(call) ?? { status: 200, body: [] };
  });
}

describe("chat", () => {
  it("shows the sources, then the answer with its citations, and opens the cited page", async () => {
    let done = false;
    const calls = api((call) => {
      if (call.path === "/api/chat") {
        done = true;
        return {
          status: 200,
          text: sse([
            ["turn", { conversation_id: "k1", ordinal: 1 }],
            ["sources", { sources: [source], warnings: [], ranked: false }],
            ["sources", { sources: [source], warnings: ["reranking_unavailable"], ranked: true }],
            ["generating", {}],
            ["delta", { text: "Meclis 7 üyeden " }],
            ["delta", { text: "oluşur. [1]" }],
            [
              "answer",
              {
                status: "answered",
                text: "Meclis 7 üyeden oluşur. [1]",
                citations: [1],
                error: null,
                stripped: 0,
              },
            ],
          ]),
        };
      }
      if (call.path === "/api/conversations") {
        return {
          status: 200,
          body: done ? [{ id: "k1", title: "Meclis kaç üyeli?", updated_at: "2026-10-01" }] : [],
        };
      }
      if (call.path === "/api/conversations/k1") {
        return { status: 200, body: { id: "k1", title: "Meclis kaç üyeli?", turns: [answered] } };
      }
      if (call.path === "/api/documents/d1/versions/1/pages/2") return { status: 200, body: page };
      if (call.method === "PUT") return { status: 204 };
      return undefined;
    });
    render(<App />);

    expect(
      await screen.findByRole("heading", { name: greeting("Editor", new Date().getHours()) }),
    ).toBeInTheDocument();
    await userEvent.type(
      screen.getByLabelText(m.chat_question_label()),
      "Meclis kaç üyeli?{Enter}",
    );

    // After the sentence it rests on.
    const [citation, ...more] = await screen.findAllByRole("button", {
      name: m.chat_citation_label({ number: "1" }),
    });
    expect(more).toHaveLength(0);
    const ask = calls.find((call) => call.path === "/api/chat");
    expect(ask?.body).toEqual({ question: "Meclis kaç üyeli?" });
    expect(ask?.headers["X-Synapse-CSRF"]).toBe("c");
    await waitFor(() => {
      expect(window.location.search).toContain("c=k1");
    });
    expect(screen.getByText(/Meclis 7 üyeden oluşur\./)).toBeInTheDocument();
    // The question heads its answer (the title bar has the conversation's title too).
    expect(
      screen.getByRole("heading", { level: 2, name: "Meclis kaç üyeli?" }),
    ).toBeInTheDocument();

    if (citation === undefined) throw new Error("no citation");
    await userEvent.click(citation);
    const viewer = await screen.findByRole("dialog", { name: m.viewer_title() });
    expect(await within(viewer).findByText(m.viewer_ocr())).toBeInTheDocument();
    expect(
      within(viewer).getByText(m.viewer_page_of({ page: "2", pages: "3" })),
    ).toBeInTheDocument();
    const marked = viewer.querySelector("mark");
    expect(marked?.textContent).toBe("Belediye meclisi\n7 üyeden oluşur.");
    await userEvent.click(within(viewer).getByRole("button", { name: m.viewer_close() }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: m.chat_feedback_helpful() }));
    await waitFor(() => {
      expect(calls.some((call) => call.method === "PUT")).toBe(true);
    });
    const feedback = calls.find((call) => call.method === "PUT");
    expect(feedback?.path).toBe("/api/conversations/k1/turns/1/feedback");
    expect(feedback?.body).toEqual({ kind: "helpful" });
  });

  it("says when nothing was found and shows the documents found as possibly related", async () => {
    api((call) => {
      if (call.path === "/api/chat") {
        return {
          status: 200,
          text: sse([
            ["turn", { conversation_id: "k2", ordinal: 1 }],
            ["sources", { sources: [source], warnings: [], ranked: true }],
            ["answer", { status: "not_found", text: "", citations: [], error: null, stripped: 0 }],
          ]),
        };
      }
      if (call.path === "/api/conversations/k2") {
        const turn = { ...answered, status: "not_found", answer: null, citations: [] };
        return { status: 200, body: { id: "k2", title: "Konser?", turns: [turn] } };
      }
      return undefined;
    });
    render(<App />);
    await userEvent.type(await screen.findByLabelText(m.chat_question_label()), "Konser?");
    await userEvent.click(screen.getByRole("button", { name: m.chat_ask() }));
    expect(await screen.findByText(m.chat_not_found())).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: m.chat_related() })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: m.chat_feedback_label() })).not.toBeInTheDocument();
  });

  it("sends a lapsed session to sign in, without asking again", async () => {
    let lapsed = false;
    const calls = fakeApi((call) => {
      if (call.path === "/api/auth/session") {
        return lapsed
          ? { status: 401, body: { error: "not_authenticated" } }
          : { status: 200, body: { auth_level: "full", csrf_token: "c", user } };
      }
      if (call.path === "/api/conversations") {
        lapsed = true;
        return { status: 401, body: { error: "not_authenticated" } };
      }
      return { status: 200, body: [] };
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: m.auth_login_title() })).toBeInTheDocument();
    expect(calls.filter((call) => call.path === "/api/conversations")).toHaveLength(1);
  });

  it("lists past conversations in the navigation, by day, and opens one", async () => {
    api((call) => {
      if (call.path === "/api/conversations") {
        const today = new Date().toISOString();
        return { status: 200, body: [{ id: "k1", title: "Meclis kaç üyeli?", updated_at: today }] };
      }
      if (call.path === "/api/conversations/k1") {
        return { status: 200, body: { id: "k1", title: "Meclis kaç üyeli?", turns: [answered] } };
      }
      return undefined;
    });
    render(<App />);
    const list = await screen.findByRole("navigation", { name: m.chat_conversations() });
    expect(
      await within(list).findByRole("heading", { name: m.chat_group_today() }),
    ).toBeInTheDocument();
    await userEvent.click(within(list).getByRole("link", { name: "Meclis kaç üyeli?" }));
    await waitFor(() => {
      expect(window.location.search).toContain("c=k1");
    });
    expect(
      await screen.findByRole("heading", { level: 2, name: "Meclis kaç üyeli?" }),
    ).toBeInTheDocument();
  });

  it("takes what is wrong with an answer from its menu", async () => {
    window.history.replaceState(null, "", "/?c=k1");
    const calls = api((call) => {
      if (call.path === "/api/conversations/k1") {
        return { status: 200, body: { id: "k1", title: "Meclis kaç üyeli?", turns: [answered] } };
      }
      if (call.method === "PUT") return { status: 204 };
      return undefined;
    });
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: m.chat_feedback_problem() }));
    await userEvent.click(
      await screen.findByRole("menuitemcheckbox", { name: m.chat_feedback_invented() }),
    );
    await waitFor(() => {
      expect(calls.find((call) => call.method === "PUT")?.body).toEqual({ kind: "invented" });
    });
    expect(await screen.findByText(m.chat_feedback_saved())).toBeInTheDocument();
  });

  it("renames and deletes a conversation", async () => {
    window.history.replaceState(null, "", "/?c=k1");
    const calls = api((call) => {
      if (call.path === "/api/conversations/k1" && call.method === "GET") {
        return { status: 200, body: { id: "k1", title: "Meclis kaç üyeli?", turns: [answered] } };
      }
      if (call.method === "PATCH" || call.method === "DELETE") return { status: 204 };
      return undefined;
    });
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: m.chat_actions() }));
    await userEvent.click(await screen.findByRole("menuitem", { name: m.chat_rename() }));
    const title = await screen.findByLabelText(m.chat_title_label());
    await userEvent.clear(title);
    await userEvent.type(title, "Meclis");
    await userEvent.click(screen.getByRole("button", { name: m.chat_save() }));
    await waitFor(() => {
      expect(calls.find((call) => call.method === "PATCH")?.body).toEqual({ title: "Meclis" });
    });

    await userEvent.click(screen.getByRole("button", { name: m.chat_actions() }));
    await userEvent.click(await screen.findByRole("menuitem", { name: m.chat_delete() }));
    expect(await screen.findByText(m.chat_delete_confirm())).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: m.common_remove() }));
    await waitFor(() => {
      expect(calls.some((call) => call.method === "DELETE" && call.path.endsWith("/k1"))).toBe(
        true,
      );
    });
    await waitFor(() => {
      expect(window.location.search).not.toContain("c=k1");
    });
  });
});

describe("chat pieces", () => {
  it("reads server-sent events however the bytes are cut", async () => {
    const text = sse([
      ["turn", { conversation_id: "k", ordinal: 1 }],
      ["delta", { text: "çok satır\nve emoji 😀" }],
    ]);
    const bytes = new TextEncoder().encode(text);
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (let i = 0; i < bytes.length; i += 3) controller.enqueue(bytes.slice(i, i + 3));
        controller.close();
      },
    });
    const events = [];
    for await (const event of serverEvents(body)) events.push(event);
    expect(events).toEqual([
      { event: "turn", data: { conversation_id: "k", ordinal: 1 } },
      { event: "delta", data: { text: "çok satır\nve emoji 😀" } },
    ]);
  });

  it("takes the citations out of an answer", () => {
    expect(answerParts("Kurul 7 üyedir. [1] Başkan seçer. [2, 3]")).toEqual([
      { text: "Kurul 7 üyedir. " },
      { citations: [1] },
      { text: " Başkan seçer. " },
      { citations: [2, 3] },
    ]);
    expect(answerParts("[sic] metin")).toEqual([{ text: "[sic] metin" }]);
  });

  it("copies an answer without its citation markers", () => {
    expect(plainAnswer("Kurul 7 üyedir. [1] Başkan seçer. [2, 3]")).toBe(
      "Kurul 7 üyedir. Başkan seçer.",
    );
    expect(plainAnswer("Süre 10 yıldır [1].")).toBe("Süre 10 yıldır.");
  });

  it("tells a file's kind by its media type, or else by its name", () => {
    expect(fileKind("application/pdf", "karar")).toBe("pdf");
    expect(fileKind(null, "Rapor.DOCX")).toBe("doc");
    expect(fileKind("application/octet-stream", "kadro.xlsx")).toBe("sheet");
    expect(fileKind(null, "Meclis Kararı")).toBe("other");
  });

  it("finds a passage on its page whatever the spacing", () => {
    const pageText =
      "Başlık\n\nBelediye   meclisi\n7 üyeden oluşur. Kısa.\nBaşka bir paragraf burada.";
    const ranges = passageRanges(pageText, "Belediye meclisi 7 üyeden oluşur.\nKısa.");
    expect(ranges.map(([start, end]) => pageText.slice(start, end))).toEqual([
      "Belediye   meclisi\n7 üyeden oluşur.",
    ]);
    expect(passageRanges(pageText, "Burada olmayan bir cümle var.")).toEqual([]);
  });

  it("marks the cited passage in a PDF page's text layer", () => {
    const layer = document.createElement("div");
    layer.innerHTML =
      "<span>Giriş.</span><br><span>Belediye meclisi</span><span>7 üyeden oluşur.</span>" +
      "<span>Son.</span>";
    expect(markPassage(layer, "Belediye meclisi 7 üyeden oluşur.")).toBe(2);
    expect([...layer.querySelectorAll(".cited")].map((span) => span.textContent)).toEqual([
      "Belediye meclisi",
      "7 üyeden oluşur.",
    ]);
  });

  it("follows the events of a turn", () => {
    let turn = started("Soru?", null);
    expect(isRunning(turn)).toBe(true);
    turn = advance(turn, { event: "turn", data: { conversation_id: "k", ordinal: 2 } });
    turn = advance(turn, {
      event: "sources",
      data: { sources: [source], warnings: [], ranked: false },
    });
    expect(turn.ranked).toBe(false);
    turn = advance(turn, {
      event: "sources",
      data: { sources: [source], warnings: [], ranked: true },
    });
    expect(turn.ranked).toBe(true);
    turn = advance(turn, { event: "queued", data: { position: 2 } });
    expect(turn.queuePosition).toBe(2);
    turn = advance(turn, { event: "generating", data: {} });
    turn = advance(turn, { event: "delta", data: { text: "Kurul 9" } });
    turn = advance(turn, { event: "retrying", data: { unsupported: ["9"] } });
    expect(turn.retrying).toBe(true);
    expect(turn.text).toBe("");
    turn = advance(turn, { event: "rewritten", data: { question: "Kurul kaç üye?" } });
    turn = advance(turn, {
      event: "answer",
      data: { status: "answered", text: "Kurul 7. [1]", citations: [1], error: null, stripped: 0 },
    });
    expect([turn.conversationId, turn.ordinal]).toEqual(["k", 2]);
    expect(turn.rewritten).toBe("Kurul kaç üye?");
    expect(isRunning(turn)).toBe(false);
    expect(isRunning(advance(started("x", null), { event: "error", data: { error: "x" } }))).toBe(
      false,
    );
  });
});
