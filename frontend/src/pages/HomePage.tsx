import { useSuspenseQuery } from "@tanstack/react-query";

import { AppShell } from "@/components/AppShell";
import { sessionQuery } from "@/features/auth/session";
import { m } from "@/paraglide/messages.js";

export function HomePage() {
  const { data: session } = useSuspenseQuery(sessionQuery);
  return (
    <AppShell>
      <h1 className="text-2xl font-semibold">
        {m.home_welcome({ name: session?.user?.display_name ?? "" })}
      </h1>
      <p className="text-muted-foreground">{m.home_next()}</p>
    </AppShell>
  );
}
