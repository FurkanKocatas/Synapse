import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState, type SubmitEvent } from "react";

import { AuthLayout, FormError } from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fieldText } from "@/lib/forms";
import { m } from "@/paraglide/messages.js";
import { getLocale, isLocale, setLocale } from "@/paraglide/runtime.js";

import { login } from "./authApi";
import { errorMessage } from "./errors";
import { placeFor, sessionQuery } from "./session";

export function LoginPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy(true);
    setError(null);
    try {
      await login(fieldText(form, "email"), fieldText(form, "password"));
      // The login response says what comes next but carries no account details; load the
      // full session so every page sees the same data.
      const session = await queryClient.query({ ...sessionQuery, staleTime: 0 });
      await navigate({ to: placeFor(session) });
      // The account's language wins over the one chosen on the sign-in page.
      const preferred = session?.user?.locale;
      if (preferred !== undefined && isLocale(preferred) && preferred !== getLocale()) {
        await setLocale(preferred);
      }
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout title={m.auth_login_title()} description={m.auth_login_subtitle()}>
      <form className="flex flex-col gap-4" onSubmit={(event) => void submit(event)}>
        <div className="flex flex-col gap-2">
          <Label htmlFor="email">{m.auth_email_label()}</Label>
          <Input id="email" name="email" type="email" autoComplete="username" required autoFocus />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="password">{m.auth_password_label()}</Label>
          <Input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
          />
        </div>
        <FormError message={error} />
        <Button type="submit" disabled={busy}>
          {busy ? m.auth_working() : m.auth_login_submit()}
        </Button>
      </form>
    </AuthLayout>
  );
}
