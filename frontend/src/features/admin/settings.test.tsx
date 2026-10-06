import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "@/App";
import { rememberCsrfToken } from "@/lib/api";
import { m } from "@/paraglide/messages.js";
import { getLocale } from "@/paraglide/runtime.js";
import { fakeApi, type Call } from "@/test/fakeApi";

import type { OrganizationSettings } from "./adminApi";

const admin = {
  id: "u1",
  email: "admin@example.org",
  display_name: "Admin",
  role: "admin",
  locale: getLocale(),
};

afterEach(() => {
  vi.unstubAllGlobals();
  rememberCsrfToken(null);
  window.history.replaceState(null, "", "/");
});

function server(initial: OrganizationSettings) {
  let settings = initial;
  const calls = fakeApi((call: Call) => {
    if (call.path === "/api/auth/session") {
      return { status: 200, body: { auth_level: "full", csrf_token: "c", user: admin } };
    }
    if (call.path === "/api/admin/settings" && call.method === "PATCH") {
      settings = { ...settings, ...(call.body as Partial<OrganizationSettings>) };
      return { status: 200, body: settings };
    }
    if (call.path === "/api/admin/settings") return { status: 200, body: settings };
    return { status: 200, body: [] };
  });
  return () => calls.filter((call) => call.method === "PATCH").map((call) => call.body);
}

describe("the organisation's settings", () => {
  it("ask another role for a second step, and keep groups of words that mean the same", async () => {
    window.history.replaceState(null, "", "/admin/settings");
    const changes = server({
      mfa_required_roles: ["editor"],
      synonyms: [["KVKK", "Kişisel Verilerin Korunması Kanunu"]],
    });
    render(<App />);

    expect(await screen.findByRole("link", { name: m.nav_admin_settings() })).toBeInTheDocument();
    const member = await screen.findByRole("checkbox", { name: new RegExp(m.role_member()) });
    expect(screen.getByRole("checkbox", { name: new RegExp(m.role_editor()) })).toBeChecked();
    const save = screen.getByRole("button", { name: m.chat_save() });
    expect(save).toBeDisabled();
    await userEvent.click(member);
    await userEvent.click(save);
    expect(await screen.findByText(m.settings_saved())).toBeInTheDocument();
    expect(changes()).toEqual([{ mfa_required_roles: ["editor", "member"] }]);

    // A word in another group is said at once, and the group cannot be added.
    const words = screen.getByLabelText(m.settings_synonyms_placeholder());
    await userEvent.type(words, "kvkk{Enter}Kurul{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      m.settings_synonyms_taken({ phrase: "kvkk" }),
    );
    expect(screen.getByRole("button", { name: m.settings_synonyms_add() })).toBeDisabled();
    await userEvent.click(
      screen.getByRole("button", { name: m.settings_synonyms_remove_phrase({ phrase: "kvkk" }) }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: m.settings_synonyms_remove_phrase({ phrase: "Kurul" }) }),
    );

    // The last word counts without Enter.
    await userEvent.type(words, "HMK{Enter}Hukuk Muhakemeleri Kanunu");
    await userEvent.click(screen.getByRole("button", { name: m.settings_synonyms_add() }));
    await waitFor(() => {
      expect(changes()).toHaveLength(2);
    });
    expect(changes()[1]).toEqual({
      synonyms: [
        ["KVKK", "Kişisel Verilerin Korunması Kanunu"],
        ["HMK", "Hukuk Muhakemeleri Kanunu"],
      ],
    });
    expect(await screen.findByText("Hukuk Muhakemeleri Kanunu")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", {
        name: `${m.settings_synonyms_remove()}: KVKK, Kişisel Verilerin Korunması Kanunu`,
      }),
    );
    await waitFor(() => {
      expect(changes()).toHaveLength(3);
    });
    expect(changes()[2]).toEqual({ synonyms: [["HMK", "Hukuk Muhakemeleri Kanunu"]] });
  });
});
