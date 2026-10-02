import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "@/App";
import { rememberCsrfToken } from "@/lib/api";
import { greeting } from "@/features/chat/ChatPage";
import { m } from "@/paraglide/messages.js";
import { getLocale } from "@/paraglide/runtime.js";
import { fakeApi } from "@/test/fakeApi";

const browser = vi.hoisted(() => ({
  supported: true,
  startAuthentication: vi.fn(),
  startRegistration: vi.fn(),
}));

vi.mock("@simplewebauthn/browser", () => ({
  browserSupportsWebAuthn: () => browser.supported,
  startAuthentication: browser.startAuthentication,
  startRegistration: browser.startRegistration,
}));

const user = {
  id: "u1",
  email: "ayse@example.org",
  display_name: "Ayşe Yılmaz",
  role: "member",
  locale: getLocale(),
};

afterEach(() => {
  vi.unstubAllGlobals();
  browser.supported = true;
  browser.startAuthentication.mockReset();
  browser.startRegistration.mockReset();
  rememberCsrfToken(null);
  window.history.replaceState(null, "", "/");
});

describe("passkeys", () => {
  it("completes a pending sign-in with a passkey", async () => {
    window.history.replaceState(null, "", "/mfa");
    let level = "pending_mfa";
    browser.startAuthentication.mockResolvedValue({ id: "cred", type: "public-key" });
    const calls = fakeApi((call) => {
      if (call.path === "/api/auth/session") {
        return level === "full"
          ? { status: 200, body: { auth_level: "full", csrf_token: "c2", user } }
          : {
              status: 200,
              body: {
                auth_level: level,
                csrf_token: "c1",
                user: null,
                second_factors: ["passkey"],
              },
            };
      }
      if (call.path === "/api/auth/mfa/passkey/options") {
        return { status: 200, body: { challenge: "abc", rpId: "synapse.test" } };
      }
      if (call.path === "/api/conversations?mode=corporate") return { status: 200, body: [] };
      level = "full";
      return { status: 200, body: { auth_level: "full", csrf_token: "c2", user: null } };
    });
    render(<App />);

    // Passkey only: the page says so, and the code field is for recovery codes.
    expect(await screen.findByText(m.auth_mfa_passkey_description())).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: m.auth_mfa_use_passkey() }));

    expect(
      await screen.findByRole("heading", {
        name: greeting(user.display_name, new Date().getHours()),
      }),
    ).toBeInTheDocument();
    expect(browser.startAuthentication).toHaveBeenCalledWith({
      optionsJSON: { challenge: "abc", rpId: "synapse.test" },
    });
    const verify = calls.find((call) => call.path === "/api/auth/mfa/passkey");
    expect(verify?.body).toEqual({ credential: { id: "cred", type: "public-key" } });
  });

  it("explains a closed passkey prompt and keeps the code form", async () => {
    window.history.replaceState(null, "", "/mfa");
    browser.startAuthentication.mockRejectedValue(new DOMException("closed", "NotAllowedError"));
    fakeApi((call) =>
      call.path === "/api/auth/session"
        ? {
            status: 200,
            body: {
              auth_level: "pending_mfa",
              csrf_token: "c",
              user: null,
              second_factors: ["totp", "passkey"],
            },
          }
        : { status: 200, body: { challenge: "abc" } },
    );
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: m.auth_mfa_use_passkey() }));
    expect(await screen.findByRole("alert")).toHaveTextContent(m.error_passkey_cancelled());
    expect(screen.getByLabelText(m.auth_code_label())).toBeInTheDocument();
  });

  it("does not offer a passkey the account does not have", async () => {
    window.history.replaceState(null, "", "/mfa");
    fakeApi(() => ({
      status: 200,
      body: { auth_level: "pending_mfa", csrf_token: "c", user: null, second_factors: ["totp"] },
    }));
    render(<App />);
    expect(await screen.findByText(m.auth_mfa_description())).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: m.auth_mfa_use_passkey() })).toBeNull();
  });

  it("adds a passkey on the account page and shows the first recovery codes", async () => {
    window.history.replaceState(null, "", "/account");
    browser.startRegistration.mockResolvedValue({ id: "new", type: "public-key" });
    let registered = false;
    const calls = fakeApi((call) => {
      if (call.path === "/api/auth/session") {
        return { status: 200, body: { auth_level: "full", csrf_token: "c", user } };
      }
      if (call.path === "/api/account/passkeys") {
        return {
          status: 200,
          body: registered
            ? [{ id: "p1", name: "Laptop", synced: true, created_at: "2026-09-28T09:00:00Z" }]
            : [],
        };
      }
      if (call.path === "/api/auth/passkeys/registration-options") {
        return { status: 200, body: { challenge: "reg" } };
      }
      if (call.path === "/api/auth/passkeys") {
        registered = true;
        return {
          status: 201,
          body: { id: "p1", recovery_codes: ["AAAA-BBBB-CCCC-DDDD"], session: null },
        };
      }
      return { status: 200, body: [] };
    });
    render(<App />);

    expect(await screen.findByText(m.account_passkeys_empty())).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(m.account_passkey_name()), "Laptop");
    await userEvent.click(screen.getByRole("button", { name: m.account_passkey_add() }));
    expect(await screen.findByText("AAAA-BBBB-CCCC-DDDD")).toBeInTheDocument();
    const sent = calls.find((call) => call.path === "/api/auth/passkeys");
    expect(sent?.body).toEqual({ credential: { id: "new", type: "public-key" }, name: "Laptop" });
  });

  it("leaves the section out when the server has no passkeys", async () => {
    window.history.replaceState(null, "", "/account");
    const calls = fakeApi((call) => {
      if (call.path === "/api/auth/session") {
        return { status: 200, body: { auth_level: "full", csrf_token: "c", user } };
      }
      if (call.path === "/api/account/passkeys") {
        return { status: 409, body: { error: "passkeys_unavailable" } };
      }
      return { status: 200, body: [] };
    });
    render(<App />);
    expect(
      await screen.findByRole("heading", { name: m.account_sessions_title() }),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(calls.some((call) => call.path === "/api/account/passkeys")).toBe(true);
    });
    expect(screen.queryByRole("heading", { name: m.account_passkeys_title() })).toBeNull();
  });
});
