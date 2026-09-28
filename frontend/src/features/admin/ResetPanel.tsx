import { useState, type SubmitEvent } from "react";

import { FormError } from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fieldText } from "@/lib/forms";
import { useAction } from "@/lib/useAction";
import { m } from "@/paraglide/messages.js";

import { adminApi, type Account } from "./adminApi";

type Done = "password" | "mfa" | null;

/** Password and second-factor reset for another user's account (docs/design/identity.md). */
export function ResetPanel({ account, refresh }: { account: Account; refresh: string[][] }) {
  const { run, error, busy } = useAction();
  const [done, setDone] = useState<Done>(null);
  const [confirming, setConfirming] = useState(false);

  async function setPassword(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setDone(null);
    const ok = await run(
      () => adminApi.resetPassword(account.id, fieldText(form, "password")),
      refresh,
    );
    if (ok) {
      form.reset();
      setDone("password");
    }
  }

  async function removeMfa() {
    setDone(null);
    setConfirming(false);
    if (await run(() => adminApi.resetMfa(account.id), refresh)) setDone("mfa");
  }

  return (
    <section className="flex flex-col gap-3 rounded-lg border p-4" aria-labelledby="reset-title">
      <h2 id="reset-title" className="font-medium">
        {m.admin_reset_title({ name: account.display_name })}
      </h2>
      <FormError message={error} />
      {done !== null && (
        <p role="status" className="text-sm">
          {done === "password" ? m.admin_reset_password_done() : m.admin_reset_mfa_done()}
        </p>
      )}

      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => void setPassword(event)}
      >
        <div className="flex flex-col gap-1">
          <Label htmlFor="reset-password">{m.account_new_password()}</Label>
          <Input
            id="reset-password"
            name="password"
            type="password"
            required
            minLength={account.has_mfa ? 8 : 15}
            autoComplete="new-password"
          />
        </div>
        <Button type="submit" disabled={busy}>
          {m.admin_reset_password_submit()}
        </Button>
      </form>

      {account.has_mfa && (
        <div className="flex flex-col gap-2">
          <p className="text-sm text-muted-foreground">{m.admin_reset_mfa_explain()}</p>
          <div className="flex gap-2">
            {confirming ? (
              <>
                <Button variant="destructive" disabled={busy} onClick={() => void removeMfa()}>
                  {m.admin_reset_mfa_confirm()}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => {
                    setConfirming(false);
                  }}
                >
                  {m.common_cancel()}
                </Button>
              </>
            ) : (
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => {
                  setConfirming(true);
                }}
              >
                {m.admin_reset_mfa_submit()}
              </Button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
