import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "@/App";
import { rememberCsrfToken } from "@/lib/api";
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
    });
    expect(adminAreas("editor")).toEqual({
      users: false,
      groups: false,
      collections: true,
      grants: false,
    });
    expect(adminAreas("member")).toEqual({
      users: false,
      groups: false,
      collections: false,
      grants: false,
    });
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
      if (call.method === "GET") {
        return {
          status: 200,
          body: [{ ...admin, status: "active", has_mfa: true }],
        };
      }
      return { status: 409, body: { error: "email_taken" } };
    });
    render(<App />);

    expect(await screen.findByText("admin@example.org")).toBeInTheDocument();
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
      if (call.method === "GET") {
        return {
          status: 200,
          body: [
            { ...admin, status: "active", has_mfa: true },
            { ...other, status: "active", has_mfa: true },
          ],
        };
      }
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
      call.path === "/api/conversations"
        ? { status: 200, body: [] }
        : {
            status: 200,
            body: { auth_level: "full", csrf_token: "c", user: { ...admin, role: "member" } },
          },
    );
    render(<App />);
    expect(await screen.findByText(m.home_welcome({ name: "Admin" }))).toBeInTheDocument();
    expect(window.location.pathname).toBe("/");
  });
});
