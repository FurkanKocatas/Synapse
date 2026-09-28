import { useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState, type SubmitEvent } from "react";

import { AuthLayout, FormError } from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";
import { signInWithPasskey, supportsPasskeys } from "@/features/passkeys/passkeyApi";
import { fieldText } from "@/lib/forms";
import { m } from "@/paraglide/messages.js";

import { verifySecondFactor } from "./authApi";
import { CodeField } from "./CodeField";
import { errorMessage } from "./errors";
import { applyAccountLocale, placeFor, sessionQuery } from "./session";

export function MfaPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: pending } = useSuspenseQuery(sessionQuery);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const factors = pending?.second_factors ?? [];
  const offerPasskey = factors.includes("passkey") && supportsPasskeys();
  const passkeyOnly = factors.length > 0 && !factors.includes("totp");

  async function complete(step: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await step();
      const session = await queryClient.query({ ...sessionQuery, staleTime: 0 });
      await navigate({ to: placeFor(session) });
      await applyAccountLocale(session);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = fieldText(event.currentTarget, "code");
    void complete(() => verifySecondFactor(code));
  }

  return (
    <AuthLayout
      title={m.auth_mfa_title()}
      description={passkeyOnly ? m.auth_mfa_passkey_description() : m.auth_mfa_description()}
    >
      <div className="flex flex-col gap-4">
        {offerPasskey && (
          <Button type="button" disabled={busy} onClick={() => void complete(signInWithPasskey)}>
            {m.auth_mfa_use_passkey()}
          </Button>
        )}
        <form className="flex flex-col gap-4" onSubmit={submit}>
          <CodeField label={m.auth_code_label()} numericOnly={false} />
          <FormError message={error} />
          <Button type="submit" variant={offerPasskey ? "outline" : "default"} disabled={busy}>
            {busy ? m.auth_working() : m.auth_mfa_submit()}
          </Button>
        </form>
      </div>
    </AuthLayout>
  );
}
