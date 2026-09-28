import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState, type SubmitEvent } from "react";

import { AuthLayout, FormError } from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";
import { fieldText } from "@/lib/forms";
import { m } from "@/paraglide/messages.js";

import { verifySecondFactor } from "./authApi";
import { CodeField } from "./CodeField";
import { errorMessage } from "./errors";
import { placeFor, sessionQuery } from "./session";

export function MfaPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = fieldText(event.currentTarget, "code");
    setBusy(true);
    setError(null);
    try {
      const session = await verifySecondFactor(code);
      await queryClient.invalidateQueries({ queryKey: sessionQuery.queryKey });
      await navigate({ to: placeFor(session) });
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout title={m.auth_mfa_title()} description={m.auth_mfa_description()}>
      <form className="flex flex-col gap-4" onSubmit={(event) => void submit(event)}>
        <CodeField label={m.auth_code_label()} numericOnly={false} />
        <FormError message={error} />
        <Button type="submit" disabled={busy}>
          {busy ? m.auth_working() : m.auth_mfa_submit()}
        </Button>
      </form>
    </AuthLayout>
  );
}
