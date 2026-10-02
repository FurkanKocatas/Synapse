import {
  SquaresFourIcon,
  TreeStructureIcon,
  UserListIcon,
  UsersThreeIcon,
  type Icon,
} from "@phosphor-icons/react";
import { useSuspenseQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { motion } from "motion/react";
import type { ReactNode } from "react";

import { Page } from "@/components/AppShell";
import { sessionQuery } from "@/features/auth/session";
import { m } from "@/paraglide/messages.js";

import { adminAreas } from "./adminApi";

interface Tab {
  to: "/admin" | "/admin/users" | "/admin/groups" | "/admin/collections";
  label: () => string;
  icon: Icon;
  // The area the role needs for this tab; the overview is there for any area.
  area: "users" | "groups" | "collections" | null;
}

const TABS: Tab[] = [
  { to: "/admin", label: m.admin_overview, icon: SquaresFourIcon, area: null },
  { to: "/admin/users", label: m.nav_admin_users, icon: UserListIcon, area: "users" },
  { to: "/admin/groups", label: m.nav_admin_groups, icon: UsersThreeIcon, area: "groups" },
  {
    to: "/admin/collections",
    label: m.nav_admin_collections,
    icon: TreeStructureIcon,
    area: "collections",
  },
];

/** A page of the administration panel: the panel's tabs (those the role may use) under its
 * title bar, the page below. */
export function AdminPage({ actions, children }: { actions?: ReactNode; children: ReactNode }) {
  const { data: session } = useSuspenseQuery(sessionQuery);
  const areas = adminAreas(session?.user?.role);
  const tabs = TABS.filter((tab) => tab.area === null || areas[tab.area]);

  return (
    <Page
      title={m.nav_admin()}
      actions={actions}
      subnav={
        <nav
          aria-label={m.nav_admin()}
          className="flex shrink-0 gap-1 overflow-x-auto border-b px-2 [scrollbar-width:none] md:px-4"
        >
          {tabs.map((tab) => (
            <Link
              key={tab.to}
              to={tab.to}
              activeOptions={{ exact: true }}
              className="group relative flex h-10 shrink-0 items-center gap-2 rounded-t-lg px-3 text-sm text-subtle-foreground transition-colors hover:text-foreground data-[status=active]:font-medium data-[status=active]:text-foreground"
            >
              {({ isActive }) => {
                const IconFor = tab.icon;
                return (
                  <>
                    <IconFor
                      weight={isActive ? "fill" : "regular"}
                      className="size-4 group-data-[status=active]:text-secondary-foreground"
                      aria-hidden="true"
                    />
                    {tab.label()}
                    {isActive && (
                      <motion.span
                        layoutId="admin-tab"
                        aria-hidden="true"
                        className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-primary"
                        transition={{ type: "spring", bounce: 0, duration: 0.35 }}
                      />
                    )}
                  </>
                );
              }}
            </Link>
          ))}
        </nav>
      }
    >
      {children}
    </Page>
  );
}
