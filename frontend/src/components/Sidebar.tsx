import {
  BooksIcon,
  ChatsCircleIcon,
  GearSixIcon,
  NotePencilIcon,
  type Icon,
} from "@phosphor-icons/react";
import { useSuspenseQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { motion } from "motion/react";

import { AccountMenu } from "@/components/AccountMenu";
import { LogoMark } from "@/components/Logo";
import { hasAdministration } from "@/features/admin/adminApi";
import { sessionQuery } from "@/features/auth/session";
import { ConversationList } from "@/features/chat/ConversationList";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";

interface NavItem {
  to: "/" | "/library" | "/admin";
  label: () => string;
  icon: Icon;
}

const CHAT: NavItem = { to: "/", label: m.nav_chat, icon: ChatsCircleIcon };
const LIBRARY: NavItem = { to: "/library", label: m.nav_library, icon: BooksIcon };
const ADMIN: NavItem = { to: "/admin", label: m.nav_admin, icon: GearSixIcon };

/** The navigation column: the product's mark, a new conversation, the pages (with the
 * administration panel for roles that have it), past conversations, and the account.
 * ``onNavigate`` closes the drawer it may sit in. */
export function Sidebar({ onNavigate }: { onNavigate?: (() => void) | undefined }) {
  const { data: session } = useSuspenseQuery(sessionQuery);
  const items = hasAdministration(session?.user?.role) ? [CHAT, LIBRARY, ADMIN] : [CHAT, LIBRARY];

  return (
    <div className="flex h-full min-h-0 flex-col gap-1 p-2.5">
      <Link
        to="/"
        search={{}}
        onClick={onNavigate}
        aria-label={m.app_name()}
        className="flex items-center gap-2.5 self-start rounded-lg px-1.5 py-1.5"
      >
        <LogoMark className="size-8" />
        <span className="leading-tight">
          <span className="block text-[15px] font-semibold tracking-tight">{m.app_name()}</span>
          <span className="block text-[11px] text-muted-foreground">{m.brand_caption()}</span>
        </span>
      </Link>
      <Link
        to="/"
        search={{}}
        state={() => ({ fresh: Date.now() })}
        onClick={onNavigate}
        className="mt-1.5 flex h-9 items-center gap-2.5 rounded-lg border bg-card px-2.5 text-sm font-medium shadow-raised transition-colors hover:border-input"
      >
        <NotePencilIcon className="size-4 text-secondary-foreground" aria-hidden="true" />
        {m.chat_new()}
      </Link>
      <nav aria-label={m.app_name()} className="mt-2 flex flex-col gap-px">
        {items.map((item) => (
          <NavLink key={item.to} item={item} onNavigate={onNavigate} />
        ))}
      </nav>
      <ConversationList onNavigate={onNavigate} />
      <div className="-mx-2.5 border-t px-2.5">
        <AccountMenu />
      </div>
    </div>
  );
}

function NavLink({ item, onNavigate }: { item: NavItem; onNavigate?: (() => void) | undefined }) {
  const IconFor = item.icon;
  return (
    <Link
      to={item.to}
      onClick={onNavigate}
      // The panel's link stays lit on every administration page.
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
