import { Menu } from "@base-ui/react/menu";
import { useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import {
  FolderOpen,
  FolderTree,
  LogOut,
  Menu as MenuIcon,
  MessageSquareText,
  PanelLeft,
  UserRound,
  Users,
  UsersRound,
  X,
  type LucideIcon,
} from "lucide-react";
import { useState, type ReactNode } from "react";

import { LanguageSwitch } from "@/components/LanguageSwitch";
import { LogoMark } from "@/components/Logo";
import { ThemeSwitch } from "@/components/ThemeSwitch";
import { adminAreas, type Role } from "@/features/admin/adminApi";
import { logout } from "@/features/auth/authApi";
import { sessionQuery } from "@/features/auth/session";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";

interface NavItem {
  to: "/" | "/library" | "/admin/users" | "/admin/groups" | "/admin/collections";
  label: () => string;
  icon: LucideIcon;
}

const MAIN: NavItem[] = [
  { to: "/", label: m.nav_chat, icon: MessageSquareText },
  { to: "/library", label: m.nav_library, icon: FolderOpen },
];

function adminItems(role: Role | undefined): NavItem[] {
  const areas = adminAreas(role);
  return [
    ...(areas.users
      ? [{ to: "/admin/users", label: m.nav_admin_users, icon: Users } as const]
      : []),
    ...(areas.groups
      ? [{ to: "/admin/groups", label: m.nav_admin_groups, icon: UsersRound } as const]
      : []),
    ...(areas.collections
      ? [{ to: "/admin/collections", label: m.nav_admin_collections, icon: FolderTree } as const]
      : []),
  ];
}

interface AppShellProps {
  title: string;
  icon?: LucideIcon;
  // Page actions, at the right of the title bar.
  actions?: ReactNode;
  // The page's own column between the navigation and the content (conversations, collections).
  pane?: ReactNode;
  paneLabel?: string;
  // Content without the centred, width-limited column (the chat lays itself out).
  wide?: boolean;
  children: ReactNode;
}

/** The frame of every signed-in page: the navigation rail, the page's own column if it has one,
 * and a title bar over the content. On narrow screens the rail and the column open as drawers. */
export function AppShell({
  title,
  icon: Icon,
  actions,
  pane,
  paneLabel,
  wide = false,
  children,
}: AppShellProps) {
  const { data: session } = useSuspenseQuery(sessionQuery);
  const [drawer, setDrawer] = useState<"nav" | "pane" | null>(null);
  const admin = adminItems(session?.user?.role);

  return (
    <div className="flex h-dvh overflow-hidden bg-background">
      <aside className="hidden w-[76px] shrink-0 flex-col items-center gap-1 bg-rail px-2 py-3 text-rail-foreground md:flex">
        <Rail admin={admin} />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b bg-background/90 px-3 backdrop-blur sm:px-4">
          <button
            type="button"
            className="rounded-lg p-2 hover:bg-muted md:hidden"
            aria-label={m.nav_open_menu()}
            onClick={() => {
              setDrawer("nav");
            }}
          >
            <MenuIcon className="size-5" aria-hidden="true" />
          </button>
          {pane !== undefined && (
            <button
              type="button"
              className="rounded-lg p-2 hover:bg-muted md:hidden"
              aria-label={paneLabel ?? title}
              onClick={() => {
                setDrawer("pane");
              }}
            >
              <PanelLeft className="size-5" aria-hidden="true" />
            </button>
          )}
          {Icon !== undefined && (
            <span className="hidden size-8 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground sm:flex">
              <Icon className="size-4" aria-hidden="true" />
            </span>
          )}
          <h1 className="min-w-0 flex-1 truncate text-base font-semibold">{title}</h1>
          <div className="flex shrink-0 items-center gap-2">
            {actions}
            <div className="hidden items-center gap-2 sm:flex">
              <LanguageSwitch compact />
              <ThemeSwitch />
            </div>
          </div>
        </header>
        <div className="flex min-h-0 flex-1">
          {pane !== undefined && (
            <aside
              aria-label={paneLabel}
              className="hidden w-72 shrink-0 flex-col overflow-y-auto border-r bg-pane md:flex"
            >
              {pane}
            </aside>
          )}
          <main className="min-w-0 flex-1 overflow-y-auto">
            {wide ? (
              children
            ) : (
              <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-4 sm:p-6">
                {children}
              </div>
            )}
          </main>
        </div>
      </div>
      {drawer !== null && (
        <div className="fixed inset-0 z-30 flex md:hidden">
          <div
            className={cn(
              "flex w-72 max-w-[85vw] flex-col overflow-y-auto shadow-xl",
              drawer === "nav" ? "bg-rail p-3 text-rail-foreground" : "bg-pane",
            )}
          >
            <button
              type="button"
              className="m-1 self-end rounded-lg p-2 opacity-80 hover:opacity-100"
              aria-label={m.viewer_close()}
              onClick={() => {
                setDrawer(null);
              }}
            >
              <X className="size-5" aria-hidden="true" />
            </button>
            {drawer === "nav" ? <Rail admin={admin} wide /> : pane}
          </div>
          <button
            type="button"
            aria-label={m.viewer_close()}
            className="flex-1 bg-black/40"
            onClick={() => {
              setDrawer(null);
            }}
          />
        </div>
      )}
    </div>
  );
}

function Rail({ admin, wide = false }: { admin: NavItem[]; wide?: boolean }) {
  return (
    <>
      <Link to="/" className="mb-3 rounded-xl p-1" aria-label={m.app_name()}>
        <LogoMark />
      </Link>
      <nav
        aria-label={m.app_name()}
        className={cn("flex w-full flex-col gap-1", wide && "gap-0.5")}
      >
        {MAIN.map((item) => (
          <RailLink key={item.to} item={item} wide={wide} />
        ))}
        {admin.length > 0 && (
          <>
            <div className="mx-2 my-2 border-t border-white/10" />
            <span className="px-1 pb-1 text-center text-[10px] font-medium tracking-wide text-rail-muted uppercase">
              {m.nav_section_admin()}
            </span>
            {admin.map((item) => (
              <RailLink key={item.to} item={item} wide={wide} />
            ))}
          </>
        )}
      </nav>
      <div
        className={cn("mt-auto flex flex-col items-center gap-3 pt-3", wide && "items-start px-2")}
      >
        {wide && (
          <div className="flex flex-col gap-2 text-foreground sm:hidden">
            <LanguageSwitch compact />
            <ThemeSwitch />
          </div>
        )}
        <AccountMenu />
      </div>
    </>
  );
}

function RailLink({ item, wide }: { item: NavItem; wide: boolean }) {
  const Icon = item.icon;
  return (
    <Link
      to={item.to}
      activeOptions={{ exact: item.to === "/", includeSearch: false }}
      className={cn(
        "flex items-center rounded-xl text-rail-muted transition-colors hover:bg-rail-active/60 hover:text-rail-foreground",
        wide ? "gap-3 px-3 py-2 text-sm" : "flex-col gap-1 px-1 py-2 text-[11px] leading-tight",
      )}
      activeProps={{ className: "bg-rail-active text-rail-foreground font-medium" }}
    >
      <Icon className="size-5 shrink-0" aria-hidden="true" />
      <span className={cn(!wide && "w-full text-center text-[10.5px] break-words hyphens-auto")}>
        {item.label()}
      </span>
    </Link>
  );
}

function initials(name: string): string {
  const letters = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word.charAt(0).toLocaleUpperCase());
  return letters.join("") || "?";
}

function AccountMenu() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: session } = useSuspenseQuery(sessionQuery);
  const user = session?.user;

  async function signOut() {
    await logout();
    queryClient.setQueryData(sessionQuery.queryKey, null);
    await navigate({ to: "/login" });
  }

  return (
    <Menu.Root>
      <Menu.Trigger
        aria-label={m.account_menu()}
        className="flex size-10 items-center justify-center rounded-full bg-highlight text-sm font-semibold text-highlight-foreground ring-2 ring-white/10 hover:ring-white/30"
      >
        {initials(user?.display_name ?? "")}
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner side="right" align="end" sideOffset={10} className="z-40">
          <Menu.Popup className="min-w-56 rounded-xl border bg-popover p-1 text-sm text-popover-foreground shadow-lg outline-none">
            <div className="px-3 py-2">
              <p className="font-medium">{user?.display_name}</p>
              <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
            </div>
            <div className="my-1 border-t" />
            <Menu.Item
              className="flex cursor-default items-center gap-2 rounded-lg px-3 py-2 outline-none data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground"
              onClick={() => void navigate({ to: "/account" })}
            >
              <UserRound className="size-4" aria-hidden="true" />
              {m.nav_account()}
            </Menu.Item>
            <Menu.Item
              className="flex cursor-default items-center gap-2 rounded-lg px-3 py-2 outline-none data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground"
              onClick={() => void signOut()}
            >
              <LogOut className="size-4" aria-hidden="true" />
              {m.auth_logout()}
            </Menu.Item>
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
}
