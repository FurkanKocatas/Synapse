import { useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";

import { LanguageSwitch } from "@/components/LanguageSwitch";
import { Button } from "@/components/ui/button";
import { logout } from "@/features/auth/authApi";
import { sessionQuery } from "@/features/auth/session";
import { m } from "@/paraglide/messages.js";

export function HomePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: session } = useSuspenseQuery(sessionQuery);

  async function signOut() {
    await logout();
    queryClient.setQueryData(sessionQuery.queryKey, null);
    await navigate({ to: "/login" });
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between border-b p-4">
        <span className="text-lg font-semibold">{m.app_name()}</span>
        <div className="flex items-center gap-4">
          <LanguageSwitch />
          <Button variant="outline" onClick={() => void signOut()}>
            {m.auth_logout()}
          </Button>
        </div>
      </header>
      <main className="mx-auto flex w-full max-w-3xl flex-col gap-2 p-8">
        <h1 className="text-2xl font-semibold">
          {m.home_welcome({ name: session?.user?.display_name ?? "" })}
        </h1>
        <p className="text-muted-foreground">{m.home_next()}</p>
      </main>
    </div>
  );
}
