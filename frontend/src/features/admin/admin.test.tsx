import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "@/App";
import { rememberCsrfToken } from "@/lib/api";
import { greeting } from "@/features/chat/ChatPage";
import { m } from "@/paraglide/messages.js";
import { fakeApi } from "@/test/fakeApi";

import { adminAreas, type Collection } from "./adminApi";
import { inTreeOrder } from "./CollectionsPage";

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
    });
    expect(adminAreas("editor")).toEqual({
      users: false,
      groups: false,
      collections: true,
      grants: false,
      audit: false,
    });
    expect(adminAreas("member")).toEqual({
      users: false,
      groups: false,
      collections: false,
      grants: false,
      audit: false,
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
    expect(within(tabs).getAllByRole("link")).toHaveLength(4);
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
