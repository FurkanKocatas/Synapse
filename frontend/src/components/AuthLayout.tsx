import type { ReactNode } from "react";

import { LanguageSwitch } from "@/components/LanguageSwitch";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { m } from "@/paraglide/messages.js";

interface AuthLayoutProps {
  title: string;
  description?: string;
  children: ReactNode;
}

/** The centred card used by every sign-in step. */
export function AuthLayout({ title, description, children }: AuthLayoutProps) {
  return (
    <div className="flex min-h-screen flex-col bg-muted/40">
      <header className="flex items-center justify-between p-4">
        <span className="text-lg font-semibold">{m.app_name()}</span>
        <LanguageSwitch />
      </header>
      <main className="flex flex-1 items-center justify-center p-4">
        <Card className="w-full max-w-sm">
          <CardHeader>
            <CardTitle>
              <h1>{title}</h1>
            </CardTitle>
            {description === undefined ? null : <CardDescription>{description}</CardDescription>}
          </CardHeader>
          <CardContent>{children}</CardContent>
        </Card>
      </main>
    </div>
  );
}

/** An error line that screen readers announce as soon as it appears. */
export function FormError({ message }: { message: string | null }) {
  if (message === null) return null;
  return (
    <p role="alert" className="text-sm text-destructive">
      {message}
    </p>
  );
}
