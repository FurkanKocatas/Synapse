import { useQuery } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";

import { FormError } from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RecoveryCodes } from "@/features/auth/RecoveryCodes";
import { ApiError } from "@/lib/api";
import { fieldText } from "@/lib/forms";
import { useAction } from "@/lib/useAction";
import { m } from "@/paraglide/messages.js";
import { getLocale } from "@/paraglide/runtime.js";

import { passkeyApi, registerPasskey, supportsPasskeys } from "./passkeyApi";

const PASSKEYS = ["account", "passkeys"];

/** The account page's passkey list. Hidden when the server has no public address set. */
export function PasskeysSection() {
  const passkeys = useQuery({ queryKey: PASSKEYS, queryFn: passkeyApi.list, retry: false });
  const { run, error, busy } = useAction();
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const format = new Intl.DateTimeFormat(getLocale(), { dateStyle: "medium" });

  // Nothing until the server has said whether passkeys are available at all.
  if (passkeys.isPending) return null;
  if (passkeys.error instanceof ApiError && passkeys.error.code === "passkeys_unavailable") {
    return null;
  }

  async function add(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const name = fieldText(form, "name") || m.passkey_default_name();
    const result: { codes: string[] | null } = { codes: null };
    const done = await run(async () => {
      result.codes = (await registerPasskey(name)).recovery_codes;
    }, [PASSKEYS]);
    if (done) {
      form.reset();
      // Only the account's first second factor comes with recovery codes.
      setRecoveryCodes(result.codes);
    }
  }

  if (recoveryCodes !== null) {
    return (
      <section className="flex flex-col gap-3 rounded-lg border p-4 md:col-span-2">
        <h2 className="font-medium">{m.auth_recovery_title()}</h2>
        <RecoveryCodes
          codes={recoveryCodes}
          onContinue={() => {
            setRecoveryCodes(null);
          }}
        />
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-3 rounded-lg border p-4" aria-labelledby="passkeys-title">
      <h2 id="passkeys-title" className="font-medium">
        {m.account_passkeys_title()}
      </h2>
      <FormError message={error} />
      {passkeys.data?.length === 0 && (
        <p className="text-sm text-muted-foreground">{m.account_passkeys_empty()}</p>
      )}
      <ul className="flex flex-col gap-2">
        {(passkeys.data ?? []).map((passkey) => (
          <li key={passkey.id} className="flex items-start justify-between gap-2 text-sm">
            <div className="flex flex-col">
              <span>{passkey.name}</span>
              <span className="text-muted-foreground">
                {passkey.synced ? m.account_passkey_synced() : m.account_passkey_device_bound()}
                {" · "}
                {m.account_passkey_added_at({ time: format.format(new Date(passkey.created_at)) })}
              </span>
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={busy}
              aria-label={`${m.common_remove()}: ${passkey.name}`}
              onClick={() => void run(() => passkeyApi.remove(passkey.id), [PASSKEYS])}
            >
              {m.common_remove()}
            </Button>
          </li>
        ))}
      </ul>
      {supportsPasskeys() ? (
        <form className="flex flex-wrap items-end gap-2" onSubmit={(event) => void add(event)}>
          <div className="flex flex-col gap-1">
            <Label htmlFor="passkey-name">{m.account_passkey_name()}</Label>
            <Input
              id="passkey-name"
              name="name"
              maxLength={100}
              placeholder={m.passkey_default_name()}
            />
          </div>
          <Button type="submit" disabled={busy}>
            {m.account_passkey_add()}
          </Button>
        </form>
      ) : (
        <p className="text-sm text-muted-foreground">{m.account_passkey_unsupported()}</p>
      )}
    </section>
  );
}
