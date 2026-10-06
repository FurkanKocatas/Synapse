import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "@/App";
import { rememberCsrfToken } from "@/lib/api";
import { greeting } from "@/features/chat/ChatPage";
import { m } from "@/paraglide/messages.js";
import { getLocale } from "@/paraglide/runtime.js";
import { fakeApi } from "@/test/fakeApi";

// The account's language matches the test environment's, so signing in does not reload the page
// to switch language (which jsdom cannot do).
const user = {
  id: "u1",
  email: "ayse@example.org",
  display_name: "Ayşe Yılmaz",
  role: "member",
  locale: getLocale(),
};

afterEach(() => {
  vi.unstubAllGlobals();
  rememberCsrfToken(null);
  window.history.replaceState(null, "", "/");
});

describe("sign-in flow", () => {
  it("sends visitors without a session to the login page, then home after signing in", async () => {
    let signedIn = false;
    const calls = fakeApi((call) => {
      if (call.path === "/api/auth/session") {
        return signedIn
          ? { status: 200, body: { auth_level: "full", csrf_token: "c2", user } }
          : { status: 401, body: { error: "not_authenticated" } };
      }
      if (call.path === "/api/conversations?mode=corporate") return { status: 200, body: [] };
      if (call.path === "/api/collections") return { status: 200, body: [] };
      signedIn = true;
      return { status: 200, body: { auth_level: "full", csrf_token: "c1", user: null } };
    });
    render(<App />);

    await userEvent.type(await screen.findByLabelText(m.auth_email_label()), user.email);
    await userEvent.type(screen.getByLabelText(m.auth_password_label()), "a long passphrase here");
    await userEvent.click(screen.getByRole("button", { name: m.auth_login_submit() }));

    expect(
      await screen.findByRole("heading", {
        name: greeting(user.display_name, new Date().getHours()),
      }),
    ).toBeInTheDocument();
    const login = calls.find((call) => call.path === "/api/auth/login");
    expect(login?.body).toEqual({ email: user.email, password: "a long passphrase here" });
  });

  it("forgets what was shown before signing out", async () => {
    let phase: "in" | "out" | "again" = "in";
    fakeApi((call) => {
      if (call.path === "/api/auth/session") {
        return phase === "out"
          ? { status: 401, body: { error: "not_authenticated" } }
          : { status: 200, body: { auth_level: "full", csrf_token: "c1", user } };
      }
      if (call.path === "/api/auth/logout") {
        phase = "out";
        return { status: 204 };
      }
      if (call.path === "/api/auth/login") {
        phase = "again";
        return { status: 200, body: { auth_level: "full", csrf_token: "c2", user: null } };
      }
      if (call.path === "/api/conversations?mode=corporate") {
        // Signed in again, the list cannot be read: only a remembered one could show.
        return phase === "in"
          ? { status: 200, body: [{ id: "k1", title: "Gizli toplantı", updated_at: "2026-10-01" }] }
          : { status: 403, body: { error: "forbidden" } };
      }
      return { status: 200, body: [] };
    });
    render(<App />);
    expect(await screen.findAllByText("Gizli toplantı")).not.toHaveLength(0);

    await userEvent.click(screen.getByRole("button", { name: m.account_menu() }));
    await userEvent.click(await screen.findByRole("menuitem", { name: m.auth_logout() }));
    await userEvent.type(await screen.findByLabelText(m.auth_email_label()), user.email);
    await userEvent.type(screen.getByLabelText(m.auth_password_label()), "a long passphrase here");
    await userEvent.click(screen.getByRole("button", { name: m.auth_login_submit() }));

    expect(
      await screen.findByRole("heading", {
        name: greeting(user.display_name, new Date().getHours()),
      }),
    ).toBeInTheDocument();
    expect(screen.queryAllByText("Gizli toplantı")).toHaveLength(0);
  });

  it("shows the server's reason when signing in fails", async () => {
    fakeApi((call) =>
      call.path === "/api/auth/session"
        ? { status: 401, body: { error: "not_authenticated" } }
        : { status: 401, body: { error: "invalid_credentials" } },
    );
    render(<App />);
    await userEvent.type(await screen.findByLabelText(m.auth_email_label()), "x@example.org");
    await userEvent.type(screen.getByLabelText(m.auth_password_label()), "wrong password here");
    await userEvent.click(screen.getByRole("button", { name: m.auth_login_submit() }));
    expect(await screen.findByRole("alert")).toHaveTextContent(m.error_invalid_credentials());
  });

  it("keeps a session that still needs its second factor on the verification page", async () => {
    fakeApi(() => ({
      status: 200,
      body: { auth_level: "pending_mfa", csrf_token: "c", user: null },
    }));
    render(<App />);
    expect(await screen.findByRole("heading", { name: m.auth_mfa_title() })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/mfa");
  });
});
