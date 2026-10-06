import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "@/App";
import type { LibraryCollection, LibraryDocument } from "@/features/library/libraryApi";
import { rememberCsrfToken } from "@/lib/api";
import { m } from "@/paraglide/messages.js";
import { answered, api, sse } from "@/test/chat";

import {
  EVERYTHING,
  folderMark,
  folderTree,
  parents,
  scopeLabel,
  toggleDocument,
  toggleFolder,
} from "./scope";

vi.mock("./PdfPage", async (original) => ({
  ...(await original<typeof import("./PdfPage")>()),
  PdfPage: () => null,
}));

afterEach(() => {
  vi.unstubAllGlobals();
  rememberCsrfToken(null);
  window.history.replaceState(null, "", "/");
});

function folder(id: string, name: string, parent: string | null, count = 0): LibraryCollection {
  return { id, parent_id: parent, name, can_write: false, document_count: count };
}

function document(id: string, collection: string, title: string): LibraryDocument {
  return {
    id,
    collection_id: collection,
    title,
    latest_version: 1,
    status: "ready",
    failure: null,
    media_type: "application/pdf",
    size_bytes: 1000,
    updated_at: "2026-10-01T09:00:00Z",
  };
}

const FOLDERS = [
  folder("f1", "Mali İşler", null, 2),
  folder("f2", "Bütçe 2026", "f1", 1),
  folder("f3", "Meclis Kararları", null, 2),
];
const COUNCIL = [document("d1", "f3", "Karar 2026-35"), document("d2", "f3", "Karar 2026-36")];

describe("where a question is searched", () => {
  it("says it in a few words", () => {
    const names = new Map(FOLDERS.map((f) => [f.id, f.name]));
    const titles = new Map([["d1", "Karar 2026-35"]]);
    expect(scopeLabel(EVERYTHING, names, titles)).toBe(m.chat_scope());
    expect(scopeLabel({ collections: ["f1"], documents: [] }, names, titles)).toBe("Mali İşler");
    expect(scopeLabel({ collections: [], documents: ["d1"] }, names, titles)).toBe("Karar 2026-35");
    expect(scopeLabel({ collections: ["f1"], documents: ["d1"] }, names, titles)).toBe(
      m.chat_scope_and({ first: "Mali İşler", second: m.chat_scope_documents({ count: "1" }) }),
    );
    expect(scopeLabel({ collections: ["f1", "f2", "f3"], documents: [] }, names, titles)).toBe(
      m.chat_scope_more_folders({ first: "Mali İşler", count: "2" }),
    );
  });

  it("chooses a folder with what is inside it, and marks the folders above a choice", () => {
    const [finance, council] = folderTree(FOLDERS);
    if (finance === undefined || council === undefined) throw new Error("no tree");
    const up = parents(FOLDERS);
    const folderOf = new Map([["d9", "f2"]]);
    let scope = toggleDocument(EVERYTHING, "d9");
    expect(folderMark(scope, finance, up, folderOf)).toBe("part");
    // Choosing the folder takes in the document chosen inside it.
    scope = toggleFolder(scope, finance, folderOf);
    expect(scope).toEqual({ collections: ["f1"], documents: [] });
    expect(folderMark(scope, finance, up, folderOf)).toBe("on");
    const [budget] = finance.children;
    if (budget === undefined) throw new Error("no child");
    expect(folderMark(scope, budget, up, folderOf)).toBe("inherited");
    expect(folderMark(scope, council, up, folderOf)).toBe("off");
    expect(toggleFolder(scope, finance, folderOf)).toEqual(EVERYTHING);
  });

  it("is chosen under the box to ask in, sent with the question and shown with it", async () => {
    const calls = api((call) => {
      if (call.path === "/api/collections") return { status: 200, body: FOLDERS };
      if (call.path === "/api/collections/f3/documents") return { status: 200, body: COUNCIL };
      if (call.path === "/api/chat") {
        return {
          status: 200,
          text: sse([
            ["turn", { conversation_id: "k1", ordinal: 1 }],
            ["sources", { sources: [], warnings: [], ranked: true }],
          ]),
        };
      }
      if (call.path === "/api/conversations/k1") {
        return { status: 200, body: { id: "k1", title: "Soru", turns: [], mode: "corporate" } };
      }
      return undefined;
    });
    render(<App />);

    await userEvent.click(
      await screen.findByRole("button", { name: m.chat_scope_button({ scope: m.chat_scope() }) }),
    );
    const panel = await screen.findByRole("dialog");
    await userEvent.click(
      within(panel).getByRole("radio", { name: new RegExp(m.chat_scope_chosen()) }),
    );
    const row = (name: string) => {
      const item = within(panel).getByRole("checkbox", { name }).closest("li");
      if (item === null) throw new Error(`no row for ${name}`);
      return item;
    };
    await userEvent.click(await within(panel).findByRole("checkbox", { name: "Mali İşler" }));
    const [openFinance] = within(row("Mali İşler")).getAllByRole("button", {
      name: m.chat_scope_open_folder(),
    });
    if (openFinance === undefined) throw new Error("no button");
    await userEvent.click(openFinance);
    // The folder inside it is chosen with it, and cannot be left out on its own.
    const budget = within(panel).getByRole("checkbox", { name: "Bütçe 2026" });
    expect(budget).toBeChecked();
    expect(budget).toBeDisabled();
    await userEvent.click(
      within(row("Meclis Kararları")).getByRole("button", { name: m.chat_scope_open_folder() }),
    );
    await userEvent.click(await within(panel).findByRole("checkbox", { name: "Karar 2026-35" }));
    const chosen = m.chat_scope_and({
      first: "Mali İşler",
      second: m.chat_scope_documents({ count: "1" }),
    });
    expect(within(panel).getByText(m.chat_scope_selected({ scope: chosen }))).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: m.chat_scope_apply() }));

    expect(
      await screen.findByRole("button", { name: m.chat_scope_button({ scope: chosen }) }),
    ).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(m.chat_question_label()), "Bütçe ne kadar?{Enter}");
    await waitFor(() => {
      expect(calls.find((call) => call.path === "/api/chat")?.body).toMatchObject({
        scope: { collections: ["f1"], documents: ["d1"] },
      });
    });
    expect(await screen.findByText(m.chat_scope_searched({ scope: chosen }))).toBeInTheDocument();
  });

  it("keeps a conversation's own scope until another is chosen", async () => {
    window.history.replaceState(null, "", "/?c=k2");
    const calls = api((call) => {
      if (call.path === "/api/collections") return { status: 200, body: FOLDERS };
      if (call.path === "/api/conversations/k2") {
        return {
          status: 200,
          body: {
            id: "k2",
            title: "Meclis kaç üyeli?",
            turns: [{ ...answered, scope: { collections: ["f3"], documents: [] } }],
            mode: "corporate",
            scope: { collections: ["f3"], documents: [] },
          },
        };
      }
      if (call.path === "/api/chat") return { status: 200, text: sse([]) };
      return undefined;
    });
    render(<App />);

    expect(
      await screen.findByText(m.chat_scope_searched({ scope: "Meclis Kararları" })),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: m.chat_scope_button({ scope: "Meclis Kararları" }) }),
    ).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(m.chat_question_label()), "Kaç üye?{Enter}");
    await waitFor(() => {
      expect(calls.some((call) => call.path === "/api/chat")).toBe(true);
    });
    // The server keeps the conversation's scope: nothing to send.
    expect(calls.find((call) => call.path === "/api/chat")?.body).not.toHaveProperty("scope");
  });
});
