import { useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { LanguageSwitch } from "@/components/LanguageSwitch";
import { Button } from "@/components/ui/button";
import { adminAreas } from "@/features/admin/adminApi";
import { logout } from "@/features/auth/authApi";
import { sessionQuery } from "@/features/auth/session";
import { m } from "@/paraglide/messages.js";

const linkClass = "rounded px-2 py-1 text-sm hover:bg-muted";
const activeClass = "bg-muted font-medium";

/** The frame around every signed-in page: navigation by role, language and sign-out. */
export function AppShell({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: session } = useSuspenseQuery(sessionQuery);
  const areas = adminAreas(session?.user?.role);

  async function signOut() {
    await logout();
    queryClient.setQueryData(sessionQuery.queryKey, null);
    await navigate({ to: "/login" });
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b p-4">
        <div className="flex flex-wrap items-center gap-4">
          <span className="text-lg font-semibold">{m.app_name()}</span>
          <nav className="flex flex-wrap gap-1" aria-label={m.app_name()}>
            <Link to="/" className={linkClass} activeProps={{ className: activeClass }}>
              {m.nav_home()}
            </Link>
            <Link to="/account" className={linkClass} activeProps={{ className: activeClass }}>
              {m.nav_account()}
            </Link>
            {areas.users ? (
              <Link
                to="/admin/users"
                className={linkClass}
                activeProps={{ className: activeClass }}
              >
                {m.nav_admin_users()}
              </Link>
            ) : null}
            {areas.groups ? (
              <Link
                to="/admin/groups"
                className={linkClass}
                activeProps={{ className: activeClass }}
              >
                {m.nav_admin_groups()}
              </Link>
            ) : null}
            {areas.collections ? (
              <Link
                to="/admin/collections"
                className={linkClass}
                activeProps={{ className: activeClass }}
              >
                {m.nav_admin_collections()}
              </Link>
            ) : null}
          </nav>
        </div>
        <div className="flex items-center gap-4">
          <LanguageSwitch />
          <Button variant="outline" onClick={() => void signOut()}>
            {m.auth_logout()}
          </Button>
        </div>
      </header>
      <main className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-4 sm:p-8">{children}</main>
    </div>
  );
}
