import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "@/App";
import { rememberCsrfToken } from "@/lib/api";
import { m } from "@/paraglide/messages.js";
import { answered, api, sse, user } from "@/test/chat";
import { fakeApi } from "@/test/fakeApi";

import { localNow, modeOf } from "./chatApi";

afterEach(() => {
  vi.unstubAllGlobals();
  rememberCsrfToken(null);
  window.history.replaceState(null, "", "/");
});

describe("the classic chat", () => {
  it("is offered only where the installation offers it", async () => {
    window.history.replaceState(null, "", "/chat");
    api(() => undefined);
    render(<App />);
    // Without the feature it is not in the navigation, and its page sends home.
    expect(await screen.findByRole("link", { name: m.nav_chat_corporate() })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: m.nav_chat_classic() })).not.toBeInTheDocument();
    await waitFor(() => {
      expect(window.location.pathname).toBe("/");
    });
  });

  it("talks freely, searching nothing, in Markdown", async () => {
    window.history.replaceState(null, "", "/chat");
    const reply = "Elbette. **Konu:** Toplantı daveti";
    const calls = fakeApi((call) => {
      if (call.path === "/api/auth/session") {
        const features = { classic_chat: true };
        return { status: 200, body: { auth_level: "full", csrf_token: "c", user, features } };
      }
      if (call.path === "/api/chat") {
        const answer = { status: "answered", text: reply, citations: [], error: null };
        return {
          status: 200,
          text: sse([
            ["turn", { conversation_id: "k5", ordinal: 1 }],
            ["generating", {}],
            ["delta", { text: reply }],
            ["answer", { ...answer, stripped: 0, kind: "general" }],
          ]),
        };
      }
      if (call.path === "/api/conversations/k5") {
        const turn = { ...answered, answer: reply, sources: [], citations: [], kind: "general" };
        return { status: 200, body: { id: "k5", title: "Davet", turns: [turn], mode: "classic" } };
      }
      return { status: 200, body: [] };
    });
    render(<App />);
    expect(await screen.findByRole("link", { name: m.nav_chat_classic() })).toBeInTheDocument();
    await userEvent.type(
      await screen.findByLabelText(m.chat_question_label()),
      "Bir davet e-postası yaz{Enter}",
    );
    expect((await screen.findByText("Konu:")).tagName).toBe("STRONG");
    expect(calls.find((call) => call.path === "/api/chat")?.body).toMatchObject({
      question: "Bir davet e-postası yaz",
      mode: "classic",
    });
    await waitFor(() => {
      expect(window.location.pathname + window.location.search).toBe("/chat?c=k5");
    });
    // The navigation lists the classic chat's own conversations.
    expect(calls.some((call) => call.path === "/api/conversations?mode=classic")).toBe(true);
    expect(screen.queryByText(m.chat_searching())).not.toBeInTheDocument();
    expect(screen.queryByText(m.chat_general_note())).not.toBeInTheDocument();
  });
});

describe("chat modes and clocks", () => {
  it("tells the mode by the page", () => {
    expect(modeOf("/chat")).toBe("classic");
    expect(modeOf("/")).toBe("corporate");
    expect(modeOf("/library")).toBe("corporate");
  });

  it("writes the user's clock with its offset", () => {
    const at = new Date(2026, 9, 2, 13, 5, 9);
    const written = localNow(at);
    expect(written.startsWith("2026-10-02T13:05:09")).toBe(true);
    expect(written).toMatch(/[+-]\d\d:\d\d$/);
  });
});
