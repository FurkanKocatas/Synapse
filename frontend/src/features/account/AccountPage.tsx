import { useQuery } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";

import { AppShell } from "@/components/AppShell";
import { FormError } from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAction } from "@/lib/useAction";
import { fieldText } from "@/lib/forms";
import { m } from "@/paraglide/messages.js";
import { getLocale } from "@/paraglide/runtime.js";

import { PasskeysSection } from "@/features/passkeys/PasskeysSection";

import { accountApi } from "./accountApi";
import { describeUserAgent } from "./userAgent";

const SESSIONS = ["account", "sessions"];

export function AccountPage() {
  return (
    <AppShell>
      <h1 className="text-2xl font-semibold">{m.nav_account()}</h1>
      <div className="grid gap-4 md:grid-cols-2">
        <PasswordForm />
        <Sessions />
        <PasskeysSection />
      </div>
    </AppShell>
  );
}

function PasswordForm() {
  const { run, error, busy } = useAction();
  const [mismatch, setMismatch] = useState(false);
  const [changed, setChanged] = useState(false);

  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const next = fieldText(form, "new");
    setChanged(false);
    setMismatch(next !== fieldText(form, "repeat"));
    if (next !== fieldText(form, "repeat")) return;
    const done = await run(
      () => accountApi.changePassword(fieldText(form, "current"), next),
      [SESSIONS],
    );
    if (done) {
      form.reset();
      setChanged(true);
    }
  }

  return (
    <form
      className="flex flex-col gap-3 rounded-lg border p-4"
      onSubmit={(event) => void submit(event)}
    >
      <h2 className="font-medium">{m.account_password_title()}</h2>
      <div className="flex flex-col gap-1">
        <Label htmlFor="current">{m.account_current_password()}</Label>
        <Input
          id="current"
          name="current"
          type="password"
          required
          autoComplete="current-password"
        />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor="new">{m.account_new_password()}</Label>
        <Input
          id="new"
          name="new"
          type="password"
          required
          minLength={8}
          autoComplete="new-password"
          aria-describedby="new-hint"
        />
        <span id="new-hint" className="text-xs text-muted-foreground">
          {m.account_password_hint()}
        </span>
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor="repeat">{m.account_repeat_password()}</Label>
        <Input id="repeat" name="repeat" type="password" required autoComplete="new-password" />
      </div>
      <FormError message={mismatch ? m.account_password_mismatch() : error} />
      {changed ? (
        <p role="status" className="text-sm">
          {m.account_password_changed()}
        </p>
      ) : null}
      <div>
        <Button type="submit" disabled={busy}>
          {m.account_save()}
        </Button>
      </div>
    </form>
  );
}

function Sessions() {
  const sessions = useQuery({ queryKey: SESSIONS, queryFn: accountApi.sessions });
  const { run, error, busy } = useAction();
  const format = new Intl.DateTimeFormat(getLocale(), { dateStyle: "medium", timeStyle: "short" });

  return (
    <section className="flex flex-col gap-3 rounded-lg border p-4">
      <h2 className="font-medium">{m.account_sessions_title()}</h2>
      <FormError message={error} />
      <ul className="flex flex-col gap-2">
        {(sessions.data ?? []).map((session) => (
          <li key={session.id} className="flex items-start justify-between gap-2 text-sm">
            <div className="flex flex-col">
              <span title={session.user_agent ?? undefined}>
                {describeUserAgent(session.user_agent) ?? m.account_unknown_device()}
                {session.client_ip ? ` · ${session.client_ip}` : ""}
              </span>
              <span className="text-muted-foreground">
                {m.account_session_last_seen({
                  time: format.format(new Date(session.last_seen_at)),
                })}
              </span>
            </div>
            {session.current ? (
              <span className="shrink-0 text-muted-foreground">{m.account_session_current()}</span>
            ) : (
              <Button
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => void run(() => accountApi.endSession(session.id), [SESSIONS])}
              >
                {m.account_session_end()}
              </Button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
