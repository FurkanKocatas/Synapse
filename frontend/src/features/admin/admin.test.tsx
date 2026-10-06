import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "@/App";
import { rememberCsrfToken } from "@/lib/api";
import { greeting } from "@/features/chat/ChatPage";
import { m } from "@/paraglide/messages.js";
import { fakeApi } from "@/test/fakeApi";

import { adminAreas, type Collection, type Operations } from "./adminApi";
import { inTreeOrder } from "./CollectionsPage";
import { issuesOf } from "./system";

afterEach(() => {
  vi.unstubAllGlobals();
  rememberCsrfToken(null);
  window.history.replaceState(null, "", "/");
});

describe("inTreeOrder", () => {
  it("lists children under their parents with increasing depth", () => {
    const collections: Collection[] = [
      { id: "b", parent_id: "a", name: "2026" },
      { id: "c", parent_id: null, name: "HR" },
      { id: "a", parent_id: null, name: "Decisions" },
    ];
    expect(inTreeOrder(collections).map(({ collection, depth }) => [collection.id, depth])).toEqual(
      [
        ["c", 0],
        ["a", 0],
        ["b", 1],
      ],
    );
  });
});

describe("adminAreas", () => {
  it("shows administration only to the roles that may use it", () => {
    expect(adminAreas("admin")).toEqual({
      users: true,
      groups: true,
      collections: true,
      grants: true,
      audit: false,
      operations: true,
    });
    expect(adminAreas("editor")).toEqual({
      users: false,
      groups: false,
      collections: true,
      grants: false,
      audit: false,
      operations: false,
    });
    expect(adminAreas("member")).toEqual({
      users: false,
      groups: false,
      collections: false,
      grants: false,
      audit: false,
      operations: false,
    });
    expect(adminAreas("auditor").audit).toBe(true);
  });
});

const admin = {
  id: "u0",
  email: "admin@example.org",
  display_name: "Admin",
  role: "admin",
  locale: "tr",
};

describe("users page", () => {
  it("lists accounts and explains a duplicate email", async () => {
    window.history.replaceState(null, "", "/admin/users");
    fakeApi((call) => {
      if (call.path === "/api/auth/session") {
        return { status: 200, body: { auth_level: "full", csrf_token: "c", user: admin } };
      }
      if (call.path === "/api/admin/users" && call.method === "GET") {
        return {
          status: 200,
          body: [{ ...admin, status: "active", has_mfa: true }],
        };
      }
      if (call.method === "GET") return { status: 200, body: [] };
      return { status: 409, body: { error: "email_taken" } };
    });
    render(<App />);

    // In the table (the navigation's account menu shows the same address).
    expect(
      await within(await screen.findByRole("table")).findByText("admin@example.org"),
    ).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(m.admin_field_display_name()), "Ayşe");
    await userEvent.type(screen.getByLabelText(m.admin_field_email()), "admin@example.org");
    await userEvent.type(screen.getByLabelText(m.admin_field_password()), "a long passphrase here");
    await userEvent.click(screen.getByRole("button", { name: m.common_create() }));
    expect(await screen.findByRole("alert")).toHaveTextContent(m.error_email_taken());
  });

  it("resets another account and asks before removing its second factor", async () => {
    window.history.replaceState(null, "", "/admin/users");
    const other = { ...admin, id: "u1", email: "other@example.org", display_name: "Other" };
    const calls = fakeApi((call) => {
      if (call.path === "/api/auth/session") {
        return { status: 200, body: { auth_level: "full", csrf_token: "c", user: admin } };
      }
      if (call.path === "/api/admin/users" && call.method === "GET") {
        return {
          status: 200,
          body: [
            { ...admin, status: "active", has_mfa: true },
            { ...other, status: "active", has_mfa: true },
          ],
        };
      }
      if (call.method === "GET") return { status: 200, body: [] };
      return { status: 204 };
    });
    render(<App />);

    // Offered once: not for one's own account.
    await userEvent.click(await screen.findByRole("button", { name: m.admin_reset_open() }));

    await userEvent.type(screen.getByLabelText(m.account_new_password()), "a new long passphrase");
    await userEvent.click(screen.getByRole("button", { name: m.admin_reset_password_submit() }));
    expect(await screen.findByRole("status")).toHaveTextContent(m.admin_reset_password_done());

    await userEvent.click(screen.getByRole("button", { name: m.admin_reset_mfa_submit() }));
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: m.admin_reset_mfa_confirm() }));
    expect(await screen.findByText(m.admin_reset_mfa_done())).toBeInTheDocument();

    const changes = calls.filter((call) => call.method !== "GET");
    expect(changes.map((call) => [call.method, call.path, call.body])).toEqual([
      ["POST", "/api/admin/users/u1/password", { password: "a new long passphrase" }],
      ["DELETE", "/api/admin/users/u1/mfa", undefined],
    ]);
  });

  it("sends members who open an administration page back home", async () => {
    window.history.replaceState(null, "", "/admin/users");
    fakeApi((call) =>
      call.path === "/api/conversations?mode=corporate"
        ? { status: 200, body: [] }
        : {
            status: 200,
            body: { auth_level: "full", csrf_token: "c", user: { ...admin, role: "member" } },
          },
    );
    render(<App />);
    expect(
      await screen.findByRole("heading", { name: greeting("Admin", new Date().getHours()) }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe("/");
  });
});

describe("administration panel", () => {
  it("sums up accounts, groups and collections, and says what needs attention", async () => {
    window.history.replaceState(null, "", "/admin");
    fakeApi((call) => {
      if (call.path === "/api/auth/session") {
        return { status: 200, body: { auth_level: "full", csrf_token: "c", user: admin } };
      }
      if (call.path === "/api/admin/users") {
        return {
          status: 200,
          body: [
            { ...admin, status: "active", has_mfa: true },
            { ...admin, id: "u1", email: "b@example.org", status: "active", has_mfa: false },
            { ...admin, id: "u2", email: "c@example.org", status: "disabled", has_mfa: false },
          ],
        };
      }
      if (call.path === "/api/admin/groups") {
        return { status: 200, body: [{ id: "g1", name: "Mali", member_count: 0 }] };
      }
      if (call.path === "/api/admin/collections") {
        return {
          status: 200,
          body: [
            { id: "c1", parent_id: null, name: "Kararlar" },
            { id: "c2", parent_id: "c1", name: "2026" },
          ],
        };
      }
      return { status: 200, body: [] };
    });
    render(<App />);

    expect(
      await screen.findByText(m.admin_stat_users_detail({ active: "2", disabled: "1" })),
    ).toBeInTheDocument();
    expect(screen.getByText(m.admin_stat_collections_detail({ top: "1" }))).toBeInTheDocument();
    // Only the active account without a second factor counts; the disabled one is listed apart.
    expect(screen.getByText(m.admin_attention_mfa({ count: "1" }))).toBeInTheDocument();
    expect(screen.getByText(m.admin_attention_disabled({ count: "1" }))).toBeInTheDocument();
    expect(screen.getByText(m.admin_attention_empty_groups({ count: "1" }))).toBeInTheDocument();
    const tabs = screen.getByRole("navigation", { name: m.nav_admin() });
    // overview, users, groups, collections and the system page
    expect(within(tabs).getAllByRole("link")).toHaveLength(5);
  });

  it("is not in the navigation of a role without administration", async () => {
    fakeApi((call) =>
      call.path === "/api/auth/session"
        ? {
            status: 200,
            body: { auth_level: "full", csrf_token: "c", user: { ...admin, role: "member" } },
          }
        : { status: 200, body: [] },
    );
    render(<App />);
    expect(
      await screen.findByRole("heading", { name: greeting("Admin", new Date().getHours()) }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: m.nav_admin() })).not.toBeInTheDocument();
  });
});

const NOW = new Date("2026-10-06T10:42:00+03:00");

function run(kind: string, ok: boolean, finished: string, details: Record<string, unknown> = {}) {
  return { kind, ok, started_at: finished, finished_at: finished, details };
}

function healthy(): Operations {
  return {
    services: [
      { name: "database", ok: true, connections: null },
      { name: "worker", ok: true, connections: 2 },
      { name: "scheduler", ok: true, connections: 1 },
      { name: "embedding", ok: true, connections: null },
      { name: "reranking", ok: true, connections: null },
      { name: "chat", ok: true, connections: null },
    ],
    queues: [],
    documents: { ready: 1240, failed: 3 },
    deleted_waiting: 0,
    retryable: 0,
    pages: {
      total: 9000,
      read_by_ocr: 4820,
      waiting_for_ocr: 0,
      not_read: 5,
      with_uncertain_identifiers: 37,
    },
    storage: {
      files_bytes: 18.4 * 1024 ** 3,
      database_bytes: 3.9 * 1024 ** 3,
      disk_free_bytes: 312 * 1024 ** 3,
      disk_total_bytes: 500 * 1024 ** 3,
    },
    runs: {
      latest: {
        backup: run("backup", true, "2026-10-06T02:30:00+03:00") as never,
        backup_verify: run("backup_verify", true, "2026-10-01T05:30:00+03:00") as never,
        audit_verify: run("audit_verify", true, "2026-10-06T04:20:00+03:00", {
          events_checked: 12304,
        }) as never,
      },
      latest_ok: {},
    },
    problems: {},
  };
}

describe("issuesOf", () => {
  it("finds nothing when all is well", () => {
    expect(issuesOf(healthy(), NOW)).toEqual([]);
  });

  it("puts what is broken first and says what each problem means", () => {
    const operations = healthy();
    operations.services[5] = { name: "chat", ok: false, connections: null };
    operations.runs.latest.backup = run("backup", false, "2026-10-06T02:30:00+03:00", {
      reason: "repository_missing",
    }) as never;
    operations.runs.latest.audit_verify = run(
      "audit_verify",
      false,
      "2026-10-06T04:20:00+03:00",
    ) as never;
    operations.retryable = 2;
    operations.storage.disk_free_bytes = 10 * 1024 ** 3;
    const issues = issuesOf(operations, NOW);
    expect(issues.map((issue) => issue.key)).toEqual([
      "audit",
      "part-chat",
      "backup-failed",
      "retryable",
      "space",
    ]);
    const backup = issues.find((issue) => issue.key === "backup-failed");
    expect(backup?.what).toContain(m.system_reason_repository_missing());
    expect(backup?.what).toContain(m.system_never());
  });

  it("reports a backup that is too old, and one never taken", () => {
    const old = healthy();
    old.runs.latest.backup = run("backup", true, "2026-10-02T02:30:00+03:00") as never;
    expect(issuesOf(old, NOW).map((issue) => issue.title)).toEqual([
      m.system_issue_backup_old({ days: "4" }),
    ]);
    const never = healthy();
    delete never.runs.latest.backup;
    expect(issuesOf(never, NOW).map((issue) => issue.key)).toEqual(["backup-never"]);
  });
});

/** The card of the page under this heading. */
function card(title: string): HTMLElement {
  const section = screen.getByRole("heading", { name: title }).closest("section");
  if (section === null) throw new Error(`no card ${title}`);
  return section;
}

describe("system page", () => {
  function serve(operations: Operations) {
    return fakeApi((call) => {
      if (call.path === "/api/auth/session") {
        return { status: 200, body: { auth_level: "full", csrf_token: "c", user: admin } };
      }
      if (call.path === "/api/admin/operations") return { status: 200, body: operations };
      if (call.path === "/api/admin/operations/retry") {
        return { status: 200, body: { reprocessing: 2, embedding: 0 } };
      }
      return { status: 200, body: [] };
    });
  }

  it("says all is well, part by part, in plain words", async () => {
    window.history.replaceState(null, "", "/admin/system");
    serve(healthy());
    render(<App />);

    expect(await screen.findByText(m.system_all_good())).toBeInTheDocument();
    expect(screen.getByText(m.system_part_worker())).toBeInTheDocument();
    const parts = card(m.system_parts());
    expect(within(parts).getAllByText(m.system_running())).toHaveLength(3);
    expect(within(parts).getAllByText(m.system_ready())).toHaveLength(3);
    expect(screen.getByText(m.system_backup_taken())).toBeInTheDocument();
    expect(screen.getByText(m.system_audit_ok())).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: m.system_retry() })).not.toBeInTheDocument();
  });

  it("lists what needs attention and retries documents that stopped halfway", async () => {
    window.history.replaceState(null, "", "/admin/system");
    const operations = healthy();
    operations.services[5] = { name: "chat", ok: false, connections: null };
    operations.retryable = 2;
    const calls = serve(operations);
    render(<App />);

    expect(await screen.findByText(m.system_attention({ count: "2" }))).toBeInTheDocument();
    expect(
      screen.getByText(m.system_issue_part_down({ part: m.system_part_chat() })),
    ).toBeInTheDocument();
    expect(screen.getByText(m.system_down())).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: m.system_retry() }));
    expect(await screen.findByRole("status")).toHaveTextContent(m.system_retried({ count: "2" }));
    expect(calls.filter((call) => call.method === "POST").map((call) => call.path)).toEqual([
      "/api/admin/operations/retry",
    ]);
  });

  it("is a tab of the panel for administrators only", async () => {
    window.history.replaceState(null, "", "/admin");
    serve(healthy());
    render(<App />);
    expect(await screen.findByRole("link", { name: m.nav_admin_system() })).toBeInTheDocument();
  });
});
