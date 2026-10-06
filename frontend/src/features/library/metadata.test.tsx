import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "@/App";
import { rememberCsrfToken } from "@/lib/api";
import { m } from "@/paraglide/messages.js";
import { getLocale } from "@/paraglide/runtime.js";
import { fakeApi, type Call } from "@/test/fakeApi";

const user = {
  id: "u1",
  email: "editor@example.org",
  display_name: "Editor",
  role: "editor",
  locale: getLocale(),
};
const folder = { id: "c1", parent_id: null, name: "Kararlar", can_write: true, document_count: 2 };
const decision = {
  id: "d1",
  collection_id: "c1",
  title: "Karar 2026-35",
  latest_version: 1,
  status: "ready",
  failure: null,
  media_type: "application/pdf",
  size_bytes: 1536,
  updated_at: "2026-09-28T09:00:00Z",
  kind: "Karar",
  document_date: "2026-03-15",
  reference: "2026/35",
  tags: ["bütçe"],
  set_by_hand: [],
};
const scan = {
  ...decision,
  id: "d2",
  title: "tarama_0412",
  kind: null,
  document_date: null,
  reference: null,
  tags: [],
};

afterEach(() => {
  vi.unstubAllGlobals();
  rememberCsrfToken(null);
  window.history.replaceState(null, "", "/");
});

function api(handler: (call: Call) => { status: number; body?: unknown } | undefined) {
  return fakeApi((call) => {
    if (call.path === "/api/auth/session") {
      return { status: 200, body: { auth_level: "full", csrf_token: "c", user } };
    }
    if (call.path === "/api/collections") return { status: 200, body: [folder] };
    return handler(call) ?? { status: 200, body: [] };
  });
}

describe("a document's details", () => {
  it("are shown under its name, searched, and corrected in their dialog", async () => {
    window.history.replaceState(null, "", "/library");
    const calls = api((call) => {
      if (call.path === "/api/collections/c1/documents") {
        return { status: 200, body: [decision, scan] };
      }
      if (call.method === "PATCH") return { status: 204 };
      return undefined;
    });
    render(<App />);

    await userEvent.click(await screen.findByRole("button", { name: "Kararlar" }));
    const row = (await screen.findByText("Karar 2026-35")).closest("li") as HTMLElement;
    expect(within(row).getByText("2026/35")).toBeInTheDocument();
    expect(within(row).getByText("bütçe")).toBeInTheDocument();
    const other = screen.getByText("tarama_0412").closest("li") as HTMLElement;
    expect(within(other).getByText(m.library_no_facts())).toBeInTheDocument();

    // The search box finds a document by its tag as by its name.
    await userEvent.type(screen.getByRole("searchbox", { name: m.library_search() }), "bütçe");
    expect(screen.queryByText("tarama_0412")).toBeNull();
    await userEvent.clear(screen.getByRole("searchbox", { name: m.library_search() }));

    await userEvent.click(
      screen.getByRole("button", { name: `${m.library_edit_info()}: Karar 2026-35` }),
    );
    const dialog = await screen.findByRole("dialog");
    // What was found on the page is marked so, to be checked.
    expect(within(dialog).getByText(m.library_info_found())).toBeInTheDocument();
    expect(within(dialog).getAllByText(m.library_found_badge())).toHaveLength(3);
    const kind = within(dialog).getByLabelText(new RegExp(m.library_field_kind()));
    await userEvent.clear(kind);
    await userEvent.type(kind, "Genelge");
    await userEvent.clear(within(dialog).getByLabelText(new RegExp(m.library_field_reference())));
    await userEvent.type(within(dialog).getByLabelText(m.library_field_tags()), "imar{Enter}");
    await userEvent.click(within(dialog).getByRole("button", { name: m.chat_save() }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    const change = calls.find((call) => call.method === "PATCH");
    expect(change?.path).toBe("/api/documents/d1");
    // Only what changed, and the number cleared.
    expect(change?.body).toEqual({ kind: "Genelge", reference: null, tags: ["bütçe", "imar"] });
  });
});
