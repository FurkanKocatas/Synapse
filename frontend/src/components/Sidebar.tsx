import {
  BooksIcon,
  ChatsCircleIcon,
  NotePencilIcon,
  TreeStructureIcon,
  UserListIcon,
  UsersThreeIcon,
  type Icon,
} from "@phosphor-icons/react";
import { useSuspenseQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { motion } from "motion/react";

import { AccountMenu } from "@/components/AccountMenu";
import { Wordmark } from "@/components/Logo";
import { adminAreas, type Role } from "@/features/admin/adminApi";
import { sessionQuery } from "@/features/auth/session";
import { ConversationList } from "@/features/chat/ConversationList";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";

interface NavItem {
  to: "/" | "/library" | "/admin/users" | "/admin/groups" | "/admin/collections";
  label: () => string;
  icon: Icon;
}

const MAIN: NavItem[] = [
  { to: "/", label: m.nav_chat, icon: ChatsCircleIcon },
  { to: "/library", label: m.nav_library, icon: BooksIcon },
];

function adminItems(role: Role | undefined): NavItem[] {
  const areas = adminAreas(role);
  const items: NavItem[] = [];
  if (areas.users) items.push({ to: "/admin/users", label: m.nav_admin_users, icon: UserListIcon });
  if (areas.groups)
    items.push({ to: "/admin/groups", label: m.nav_admin_groups, icon: UsersThreeIcon });
  if (areas.collections) {
    items.push({
      to: "/admin/collections",
      label: m.nav_admin_collections,
      icon: TreeStructureIcon,
    });
  }
  return items;
}

/** The navigation column: a new conversation, the pages, past conversations, administration
 * for roles that have it, and the account. ``onNavigate`` closes the drawer it may sit in. */
export function Sidebar({ onNavigate }: { onNavigate?: (() => void) | undefined }) {
  const { data: session } = useSuspenseQuery(sessionQuery);
  const admin = adminItems(session?.user?.role);

  return (
    <div className="flex h-full min-h-0 flex-col gap-1 p-2.5">
      <Link
        to="/"
        search={{}}
        onClick={onNavigate}
        aria-label={m.app_name()}
        className="flex h-10 items-center self-start rounded-lg px-1.5"
      >
        <Wordmark />
      </Link>
      <Link
        to="/"
        search={{}}
        state={() => ({ fresh: Date.now() })}
        onClick={onNavigate}
        className="mt-1 flex h-9 items-center gap-2.5 rounded-lg border bg-card px-2.5 text-sm font-medium shadow-raised transition-colors hover:border-input"
      >
        <NotePencilIcon className="size-4 text-secondary-foreground" aria-hidden="true" />
        {m.chat_new()}
      </Link>
      <nav aria-label={m.app_name()} className="mt-2 flex flex-col gap-px">
        {MAIN.map((item) => (
          <NavLink key={item.to} item={item} onNavigate={onNavigate} />
        ))}
      </nav>
      <ConversationList onNavigate={onNavigate} />
      {admin.length > 0 && (
        <div className="-mx-2.5 border-t px-2.5 pt-1">
          <p className="px-2.5 pt-2.5 pb-1 text-xs font-medium text-muted-foreground">
            {m.nav_section_admin()}
          </p>
          <nav aria-label={m.nav_section_admin()} className="flex flex-col gap-px">
            {admin.map((item) => (
              <NavLink key={item.to} item={item} onNavigate={onNavigate} />
            ))}
          </nav>
        </div>
      )}
      <AccountMenu />
    </div>
  );
}

function NavLink({ item, onNavigate }: { item: NavItem; onNavigate?: (() => void) | undefined }) {
  const IconFor = item.icon;
  return (
    <Link
      to={item.to}
      onClick={onNavigate}
      activeOptions={{ exact: item.to === "/", includeSearch: false }}
      className="group relative flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-sm text-subtle-foreground transition-colors hover:text-foreground data-[status=active]:font-medium data-[status=active]:text-foreground"
    >
      {({ isActive }) => (
        <>
          {isActive ? (
            <motion.span
              layoutId="nav-active"
              aria-hidden="true"
              className="absolute inset-0 rounded-lg border bg-card shadow-raised"
              transition={{ type: "spring", bounce: 0, duration: 0.35 }}
            />
          ) : (
            <span
              aria-hidden="true"
              className="absolute inset-0 rounded-lg transition-colors group-hover:bg-accent"
            />
          )}
          <IconFor
            weight={isActive ? "fill" : "regular"}
            className={cn("relative size-[18px]", isActive && "text-secondary-foreground")}
            aria-hidden="true"
          />
          <span className="relative">{item.label()}</span>
        </>
      )}
    </Link>
  );
}
