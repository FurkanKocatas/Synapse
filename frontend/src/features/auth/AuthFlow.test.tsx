import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "@/App";
import { rememberCsrfToken } from "@/lib/api";
import { m } from "@/paraglide/messages.js";
import { fakeApi } from "@/test/fakeApi";

const user = {
  id: "u1",
  email: "ayse@example.org",
  display_name: "Ayşe Yılmaz",
  role: "member",
  locale: "tr",
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
      signedIn = true;
      return { status: 200, body: { auth_level: "full", csrf_token: "c1", user: null } };
    });
    render(<App />);

    await userEvent.type(await screen.findByLabelText(m.auth_email_label()), user.email);
    await userEvent.type(screen.getByLabelText(m.auth_password_label()), "a long passphrase here");
    await userEvent.click(screen.getByRole("button", { name: m.auth_login_submit() }));

    expect(
      await screen.findByText(m.home_welcome({ name: user.display_name })),
    ).toBeInTheDocument();
    const login = calls.find((call) => call.path === "/api/auth/login");
    expect(login?.body).toEqual({ email: user.email, password: "a long passphrase here" });
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
