import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "@/App";
import { greeting } from "@/features/chat/ChatPage";
import { rememberCsrfToken } from "@/lib/api";
import { m } from "@/paraglide/messages.js";
import { answered, api, page, source, sse, user } from "@/test/chat";
import { fakeApi } from "@/test/fakeApi";

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
      if (call.path === "/api/conversations?mode=corporate") {
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
    expect(ask?.body).toMatchObject({ question: "Meclis kaç üyeli?", mode: "corporate" });
    // The user's clock with its offset, for the model to know the day.
    expect((ask?.body as { now: string }).now).toMatch(
      /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$/,
    );
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
      if (call.path === "/api/conversations?mode=corporate") {
        lapsed = true;
        return { status: 401, body: { error: "not_authenticated" } };
      }
      return { status: 200, body: [] };
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: m.auth_login_title() })).toBeInTheDocument();
    expect(calls.filter((call) => call.path === "/api/conversations?mode=corporate")).toHaveLength(
      1,
    );
  });

  it("lists past conversations in the navigation, by day, and opens one", async () => {
    api((call) => {
      if (call.path === "/api/conversations?mode=corporate") {
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

  it("answers a greeting in conversation, with no sources", async () => {
    api((call) => {
      if (call.path === "/api/chat") {
        return {
          status: 200,
          text: sse([
            ["turn", { conversation_id: "k3", ordinal: 1 }],
            ["generating", {}],
            ["delta", { text: "Merhaba! " }],
            ["delta", { text: "Ne sormak istersiniz?" }],
            [
              "answer",
              {
                status: "answered",
                text: "Merhaba! Ne sormak istersiniz?",
                citations: [],
                error: null,
                stripped: 0,
                kind: "conversation",
              },
            ],
          ]),
        };
      }
      if (call.path === "/api/conversations/k3") {
        const turn = {
          ...answered,
          question: "Selam",
          answer: "Merhaba! Ne sormak istersiniz?",
          sources: [],
          citations: [],
          kind: "conversation",
        };
        return { status: 200, body: { id: "k3", title: "Selam", turns: [turn] } };
      }
      return undefined;
    });
    render(<App />);
    await userEvent.type(await screen.findByLabelText(m.chat_question_label()), "Selam{Enter}");
    expect(await screen.findByText("Merhaba! Ne sormak istersiniz?")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: m.chat_sources() })).not.toBeInTheDocument();
    expect(screen.queryByText(m.chat_general_note())).not.toBeInTheDocument();
  });

  it("marks an answer from general knowledge as not resting on the documents", async () => {
    window.history.replaceState(null, "", "/?c=k4");
    api((call) => {
      if (call.path === "/api/conversations/k4") {
        const turn = {
          ...answered,
          question: "Fotosentez nedir?",
          answer: "Bitkilerin ışıkla besin üretmesidir.",
          citations: [],
          kind: "general",
        };
        return { status: 200, body: { id: "k4", title: "Fotosentez", turns: [turn] } };
      }
      return undefined;
    });
    render(<App />);
    expect(await screen.findByText(m.chat_general_note())).toBeInTheDocument();
    // What the search found is not shown under it.
    expect(screen.queryByRole("region", { name: m.chat_sources() })).not.toBeInTheDocument();
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
