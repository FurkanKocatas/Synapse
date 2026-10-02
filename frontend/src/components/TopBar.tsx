import { GearSixIcon, ListIcon } from "@phosphor-icons/react";
import { useSuspenseQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { AccountMenu } from "@/components/AccountMenu";
import { HistoryButtons } from "@/components/HistoryButtons";
import { LogoMark } from "@/components/Logo";
import { hasAdministration } from "@/features/admin/adminApi";
import { sessionQuery } from "@/features/auth/session";
import { m } from "@/paraglide/messages.js";

/** The bar across the top of the signed-in pages. Three equal-width parts, so the mark stays
 * in the middle whatever the page's title: back and forward with the page's title and actions
 * (filled by Page), the mark, and administration with the account menu on the right. */
export function TopBar({
  titleSlot,
  onOpenNavigation,
}: {
  // Receives the element the page's title is rendered into.
  titleSlot: (element: HTMLElement | null) => void;
  onOpenNavigation: () => void;
}) {
  const { data: session } = useSuspenseQuery(sessionQuery);

  return (
    <header className="grid h-15 shrink-0 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3 border-b bg-sidebar px-2 md:px-5">
      <div className="flex min-w-0 items-center gap-2">
        <button
          type="button"
          className="shrink-0 rounded-lg p-1.5 text-subtle-foreground hover:bg-accent hover:text-foreground md:hidden"
          aria-label={m.nav_open_menu()}
          onClick={onOpenNavigation}
        >
          <ListIcon className="size-5" aria-hidden="true" />
        </button>
        <HistoryButtons />
        <span aria-hidden="true" className="mx-1 hidden h-5 w-px shrink-0 bg-border sm:block" />
        <div ref={titleSlot} className="hidden min-w-0 items-center gap-2 sm:flex" />
      </div>

      <Link
        to="/"
        search={{}}
        aria-label={m.app_name()}
        className="group/logo flex items-center gap-3 rounded-xl px-2 py-1 outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <LogoMark className="size-9 transition-transform duration-500 group-hover/logo:rotate-[-8deg] group-hover/logo:scale-105" />
        <span className="hidden leading-tight sm:block">
          <span className="block text-[17px] font-semibold tracking-tight">{m.app_name()}</span>
          <span className="block text-xs text-muted-foreground">{m.brand_caption()}</span>
        </span>
      </Link>

      <div className="flex items-center justify-end gap-1.5">
        {hasAdministration(session?.user?.role) && (
          <Link
            to="/admin"
            aria-label={m.nav_admin()}
            title={m.nav_admin()}
            className="flex h-9 items-center gap-2 rounded-lg border border-transparent px-2.5 text-sm text-subtle-foreground transition-colors hover:bg-accent hover:text-foreground data-[status=active]:border-border data-[status=active]:bg-card data-[status=active]:font-medium data-[status=active]:text-foreground data-[status=active]:shadow-raised"
          >
            {({ isActive }) => (
              <>
                <GearSixIcon
                  weight={isActive ? "fill" : "regular"}
                  className={isActive ? "size-[18px] text-secondary-foreground" : "size-[18px]"}
                  aria-hidden="true"
                />
                <span aria-hidden="true" className="hidden lg:inline">
                  {m.nav_admin()}
                </span>
              </>
            )}
          </Link>
        )}
        <AccountMenu />
      </div>
    </header>
  );
}
