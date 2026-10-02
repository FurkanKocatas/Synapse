import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "@/App";
import { rememberCsrfToken } from "@/lib/api";
import { m } from "@/paraglide/messages.js";
import { getLocale } from "@/paraglide/runtime.js";
import { fakeApi, type Call } from "@/test/fakeApi";

import { formatSize } from "./labels";

const user = {
  id: "u1",
  email: "editor@example.org",
  display_name: "Editor",
  role: "editor",
  locale: getLocale(),
};

const writable = { id: "c1", parent_id: null, name: "Kararlar", can_write: true };
const readable = { id: "c2", parent_id: null, name: "Yönetmelikler", can_write: false };
const document = {
  id: "d1",
  collection_id: "c1",
  title: "Karar 2026-35",
  latest_version: 1,
  status: "parsed",
  failure: null,
  media_type: "application/pdf",
  size_bytes: 1536,
  updated_at: "2026-09-28T09:00:00Z",
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
    if (call.path === "/api/collections") return { status: 200, body: [writable, readable] };
    return handler(call) ?? { status: 200, body: [] };
  });
}

describe("library", () => {
  it("lists documents and uploads files as raw bodies, reporting each failure", async () => {
    window.history.replaceState(null, "", "/library");
    const calls = api((call) => {
      if (call.method === "POST" && call.path.includes("filename=kopya.pdf")) {
        return { status: 409, body: { error: "duplicate_document" } };
      }
      if (call.method === "POST") return { status: 201, body: { id: "d2" } };
      if (call.path === "/api/collections/c1/documents") return { status: 200, body: [document] };
      return undefined;
    });
    render(<App />);

    await userEvent.click(await screen.findByRole("button", { name: "Kararlar" }));
    const row = (await screen.findByText("Karar 2026-35")).closest("li") as HTMLElement;
    // Searchable by its words already: ready, as far as the user can tell.
    expect(within(row).getAllByText(m.status_ready()).length).toBeGreaterThan(0);
    expect(within(row).getAllByText(formatSize(1536, getLocale())).length).toBeGreaterThan(0);
    const download = screen.getByRole("link", { name: `${m.library_download()}: Karar 2026-35` });
    expect(download).toHaveAttribute("href", "/api/documents/d1/versions/1/file");

    const files = [
      new File(["%PDF-1.7"], "Yeni Karar.pdf", { type: "application/pdf" }),
      new File(["%PDF-1.7"], "kopya.pdf", { type: "application/pdf" }),
    ];
    await userEvent.upload(screen.getByLabelText(m.library_upload()), files);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      m.library_upload_failed({ name: "kopya.pdf", reason: m.error_duplicate_document() }),
    );
    expect(screen.getByRole("status")).toHaveTextContent(m.library_uploaded({ count: "1" }));
    const uploads = calls.filter((call) => call.method === "POST");
    expect(uploads.map((call) => call.path)).toEqual([
      "/api/collections/c1/documents?filename=Yeni%20Karar.pdf",
      "/api/collections/c1/documents?filename=kopya.pdf",
    ]);
    expect(uploads[0]?.raw).toBe(files[0]);
    expect(uploads[0]?.headers["Content-Type"]).toBe("application/octet-stream");
  });

  it("offers no upload or delete where the user can only read", async () => {
    window.history.replaceState(null, "", "/library");
    api((call) =>
      call.path === "/api/collections/c2/documents"
        ? { status: 200, body: [{ ...document, collection_id: "c2" }] }
        : undefined,
    );
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Yönetmelikler" }));
    expect(await screen.findByText(m.library_read_only())).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: m.library_upload() })).toBeNull();
    expect(
      screen.queryByRole("button", { name: `${m.library_delete()}: Karar 2026-35` }),
    ).toBeNull();
  });

  it("asks before deleting", async () => {
    window.history.replaceState(null, "", "/library");
    const calls = api((call) =>
      call.path === "/api/collections/c1/documents"
        ? { status: 200, body: [document] }
        : call.method === "DELETE"
          ? { status: 204 }
          : undefined,
    );
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Kararlar" }));
    await userEvent.click(
      await screen.findByRole("button", { name: `${m.library_delete()}: Karar 2026-35` }),
    );
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);
    expect(await screen.findByRole("alertdialog")).toHaveTextContent(m.library_delete_explain());
    await userEvent.click(screen.getByRole("button", { name: m.library_delete_confirm() }));
    await waitFor(() => {
      expect(calls.filter((call) => call.method === "DELETE").map((c) => c.path)).toEqual([
        "/api/documents/d1",
      ]);
    });
  });
});

describe("opening a document", () => {
  it("shows a ready document's first page beside the list", async () => {
    window.history.replaceState(null, "", "/library");
    const calls = api((call) => {
      if (call.path === "/api/collections/c1/documents") {
        return { status: 200, body: [{ ...document, status: "ready" }] };
      }
      if (call.path === "/api/documents/d1/versions/1/pages/1") {
        return {
          status: 200,
          body: {
            document_id: "d1",
            title: "Karar 2026-35",
            version: 1,
            number: 1,
            pages: 3,
            kind: "page",
            label: null,
            text: "Madde 1. Kurul yedi üyeden oluşur.",
            text_source: "layer",
            media_type: "text/plain",
            chunks: [],
          },
        };
      }
      return undefined;
    });
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Karar 2026-35" }));
    const viewer = await screen.findByRole("dialog", { name: m.viewer_title() });
    expect(
      await within(viewer).findByText("Madde 1. Kurul yedi üyeden oluşur."),
    ).toBeInTheDocument();
    expect(
      within(viewer).getByText(m.viewer_page_of({ page: "1", pages: "3" })),
    ).toBeInTheDocument();
    expect(calls.some((call) => call.path.endsWith("/pages/1"))).toBe(true);
  });

  it("is not offered while the document is still being read, which says why it takes long", async () => {
    window.history.replaceState(null, "", "/library");
    api((call) =>
      call.path === "/api/collections/c1/documents"
        ? { status: 200, body: [{ ...document, status: "ocr" }] }
        : undefined,
    );
    render(<App />);
    expect(await screen.findByText(m.library_ocr_note())).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Karar 2026-35" })).toBeNull();
    expect(screen.queryByRole("button", { name: `${m.library_open()}: Karar 2026-35` })).toBeNull();
  });
});

describe("failed documents", () => {
  it("are listed alone when the filter asks for them", async () => {
    window.history.replaceState(null, "", "/library");
    api((call) =>
      call.path === "/api/collections/c1/documents"
        ? {
            status: 200,
            body: [
              document,
              { ...document, id: "d2", title: "Bozuk tarama", status: "failed", failure: "empty" },
            ],
          }
        : undefined,
    );
    render(<App />);
    expect(await screen.findByText("Karar 2026-35")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: m.library_filter_failed() }));
    expect(screen.getByText("Bozuk tarama")).toBeInTheDocument();
    expect(screen.queryByText("Karar 2026-35")).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(m.library_search()), "karar");
    expect(screen.getByText(m.library_no_match())).toBeInTheDocument();
  });
  it("say why they failed", async () => {
    window.history.replaceState(null, "", "/library");
    api((call) =>
      call.path === "/api/collections/c1/documents"
        ? { status: 200, body: [{ ...document, status: "failed", failure: "encrypted" }] }
        : undefined,
    );
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Kararlar" }));
    expect(await screen.findByText(m.failure_encrypted())).toBeInTheDocument();
  });
});

describe("formatSize", () => {
  it("uses the locale's number format", () => {
    expect(formatSize(512, "en")).toBe("512 B");
    expect(formatSize(1536, "en")).toBe("1.5 KB");
    expect(formatSize(1536, "tr")).toBe("1,5 KB");
    expect(formatSize(25 * 1024 * 1024, "tr")).toBe("25 MB");
  });
});
