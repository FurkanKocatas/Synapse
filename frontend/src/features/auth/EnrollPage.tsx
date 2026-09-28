import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState, type SubmitEvent } from "react";

import { AuthLayout, FormError } from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";
import { registerPasskey, supportsPasskeys } from "@/features/passkeys/passkeyApi";
import { fieldText } from "@/lib/forms";
import { m } from "@/paraglide/messages.js";

import { confirmTotpEnrollment, startTotpEnrollment } from "./authApi";
import { CodeField } from "./CodeField";
import { errorMessage } from "./errors";
import { QrCode } from "./QrCode";
import { RecoveryCodes } from "./RecoveryCodes";
import { applyAccountLocale, sessionQuery } from "./session";

export function EnrollPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);

  // Starting enrollment creates a new secret on the server, so it must run exactly once per
  // visit: never again on refocus or remount, or the QR code shown would stop matching.
  const enrollment = useQuery({
    queryKey: ["totp-enrollment"],
    queryFn: startTotpEnrollment,
    staleTime: Infinity,
    gcTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
  });

  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = fieldText(event.currentTarget, "code");
    setBusy(true);
    setError(null);
    try {
      const confirmed = await confirmTotpEnrollment(code);
      setRecoveryCodes(confirmed.recovery_codes);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  async function enrollWithPasskey() {
    setBusy(true);
    setError(null);
    try {
      const registered = await registerPasskey(m.passkey_default_name());
      // Recovery codes come with the account's first second factor, which this is.
      setRecoveryCodes(registered.recovery_codes ?? []);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    const session = await queryClient.query({ ...sessionQuery, staleTime: 0 });
    await navigate({ to: "/" });
    await applyAccountLocale(session);
  }

  if (recoveryCodes !== null) {
    return (
      <AuthLayout title={m.auth_recovery_title()}>
        <RecoveryCodes codes={recoveryCodes} onContinue={() => void finish()} />
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title={m.auth_enroll_title()} description={m.auth_enroll_description()}>
      {enrollment.isError ? (
        <FormError message={errorMessage(enrollment.error)} />
      ) : enrollment.data === undefined ? (
        <p className="text-sm text-muted-foreground">{m.auth_working()}</p>
      ) : (
        <form className="flex flex-col gap-4" onSubmit={(event) => void submit(event)}>
          <QrCode value={enrollment.data.provisioning_uri} label={m.auth_enroll_qr_label()} />
          <div className="flex flex-col gap-1 text-sm">
            <span className="text-muted-foreground">{m.auth_enroll_manual()}</span>
            <code className="break-all rounded bg-muted p-2 font-mono">
              {enrollment.data.secret}
            </code>
          </div>
          <CodeField label={m.auth_enroll_code_label()} numericOnly />
          <FormError message={error} />
          <Button type="submit" disabled={busy}>
            {busy ? m.auth_working() : m.auth_enroll_submit()}
          </Button>
        </form>
      )}
      {supportsPasskeys() && (
        <section className="mt-6 flex flex-col gap-2 border-t pt-4" aria-labelledby="passkey-title">
          <h2 id="passkey-title" className="font-medium">
            {m.auth_enroll_passkey_title()}
          </h2>
          <p className="text-sm text-muted-foreground">{m.auth_enroll_passkey_description()}</p>
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={() => void enrollWithPasskey()}
          >
            {m.passkey_create()}
          </Button>
        </section>
      )}
    </AuthLayout>
  );
}
