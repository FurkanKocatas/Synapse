import {
  BooksIcon,
  BuildingsIcon,
  ChatCircleDotsIcon,
  NotePencilIcon,
  type Icon,
} from "@phosphor-icons/react";
import { useSuspenseQuery } from "@tanstack/react-query";
import { Link, useLocation } from "@tanstack/react-router";
import { motion } from "motion/react";

import { sessionQuery } from "@/features/auth/session";
import { CHAT_PATH, modeOf } from "@/features/chat/chatApi";
import { ConversationList } from "@/features/chat/ConversationList";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";

interface NavItem {
  to: "/" | "/chat" | "/library";
  label: () => string;
  icon: Icon;
}

const CORPORATE: NavItem = { to: "/", label: m.nav_chat_corporate, icon: BuildingsIcon };
const CLASSIC: NavItem = { to: "/chat", label: m.nav_chat_classic, icon: ChatCircleDotsIcon };
const LIBRARY: NavItem = { to: "/library", label: m.nav_library, icon: BooksIcon };

/** The navigation column under the top bar: a new conversation (in the chat that is open), the
 * two chats and the library, and that chat's past conversations. ``onNavigate`` closes the
 * drawer it may sit in. */
export function Sidebar({ onNavigate }: { onNavigate?: (() => void) | undefined }) {
  const { data: session } = useSuspenseQuery(sessionQuery);
  const { pathname } = useLocation();
  const classic = session?.features?.classic_chat === true;
  const items = classic ? [CORPORATE, CLASSIC, LIBRARY] : [CORPORATE, LIBRARY];
  return (
    <div className="flex h-full min-h-0 flex-col gap-1 p-3">
      <Link
        to={CHAT_PATH[modeOf(pathname)]}
        search={{}}
        state={() => ({ fresh: Date.now() })}
        onClick={onNavigate}
        className="group flex h-11 shrink-0 items-center gap-3 rounded-xl bg-primary px-3.5 text-[15px] font-medium text-primary-foreground shadow-raised transition-[background-color,transform,box-shadow] hover:-translate-y-px hover:bg-primary-hover hover:shadow-floating active:translate-y-0"
      >
        <NotePencilIcon
          weight="bold"
          className="size-[18px] transition-transform duration-300 group-hover:-rotate-12"
          aria-hidden="true"
        />
        {m.chat_new()}
      </Link>
      <nav aria-label={m.app_name()} className="mt-3 flex flex-col gap-0.5">
        {items.map((item) => (
          <NavLink key={item.to} item={item} onNavigate={onNavigate} />
        ))}
      </nav>
      <ConversationList onNavigate={onNavigate} />
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
      className="group relative flex h-10 items-center gap-3 rounded-xl px-3 text-[15px] text-subtle-foreground transition-colors hover:text-foreground data-[status=active]:font-medium data-[status=active]:text-foreground"
    >
      {({ isActive }) => (
        <>
          {isActive ? (
            <motion.span
              layoutId="nav-active"
              aria-hidden="true"
              className="absolute inset-0 rounded-xl border bg-card shadow-raised"
              transition={{ type: "spring", bounce: 0, duration: 0.35 }}
            />
          ) : (
            <span
              aria-hidden="true"
              className="absolute inset-0 rounded-xl transition-colors group-hover:bg-accent"
            />
          )}
          <IconFor
            weight={isActive ? "fill" : "regular"}
            className={cn(
              "relative size-5 transition-transform duration-300 group-hover:scale-110",
              isActive && "text-secondary-foreground",
            )}
            aria-hidden="true"
          />
          <span className="relative">{item.label()}</span>
        </>
      )}
    </Link>
  );
}
