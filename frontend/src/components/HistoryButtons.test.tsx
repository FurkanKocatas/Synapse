import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "@/App";
import { rememberCsrfToken } from "@/lib/api";
import { m } from "@/paraglide/messages.js";
import { getLocale } from "@/paraglide/runtime.js";
import { fakeApi } from "@/test/fakeApi";

const user = {
  id: "u1",
  email: "member@example.org",
  display_name: "Member",
  role: "member",
  locale: getLocale(),
};

beforeEach(() => {
  sessionStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  rememberCsrfToken(null);
  window.history.replaceState(null, "", "/");
});

describe("back and forward", () => {
  it("go through the pages the user opened, as the browser's arrows do", async () => {
    window.history.replaceState(null, "", "/library");
    fakeApi((call) =>
      call.path === "/api/auth/session"
        ? { status: 200, body: { auth_level: "full", csrf_token: "c", user } }
        : { status: 200, body: [] },
    );
    render(<App />);
    const back = await screen.findByRole("button", { name: m.nav_back() });
    const forward = screen.getByRole("button", { name: m.nav_forward() });
    // The first page of the app: nothing to go back to in it.
    expect(back).toBeDisabled();
    expect(forward).toBeDisabled();

    await userEvent.click(screen.getByRole("link", { name: m.nav_chat_corporate() }));
    await waitFor(() => {
      expect(window.location.pathname).toBe("/");
    });
    expect(back).toBeEnabled();
    expect(forward).toBeDisabled();

    await userEvent.click(back);
    await waitFor(() => {
      expect(window.location.pathname).toBe("/library");
    });
    expect(back).toBeDisabled();
    expect(forward).toBeEnabled();

    await userEvent.click(forward);
    await waitFor(() => {
      expect(window.location.pathname).toBe("/");
    });
    expect(forward).toBeDisabled();
  });
});
