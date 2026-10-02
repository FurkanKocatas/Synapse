import {
  CheckCircleIcon,
  FolderPlusIcon,
  ShieldCheckIcon,
  ShieldWarningIcon,
  TreeStructureIcon,
  UserListIcon,
  UserPlusIcon,
  UsersThreeIcon,
  WarningIcon,
  type Icon,
} from "@phosphor-icons/react";
import { useQuery, useSuspenseQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import type { CSSProperties, ReactNode } from "react";

import { CountUp } from "@/components/reactbits/CountUp";
import { SpotlightCard } from "@/components/reactbits/SpotlightCard";

import { sessionQuery } from "@/features/auth/session";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";
import { getLocale } from "@/paraglide/runtime.js";

import { AdminPage } from "./AdminFrame";
import { adminApi, adminAreas, ROLES, type Account, type Group } from "./adminApi";
import { roleLabel } from "./labels";

type AreaPath = "/admin/users" | "/admin/groups" | "/admin/collections";

/** The panel's first page: the state of accounts, groups and collections at a glance, what
 * needs attention, and the usual next steps. Each part is there only for roles that have it. */
export function AdminOverview() {
  const { data: session } = useSuspenseQuery(sessionQuery);
  const areas = adminAreas(session?.user?.role);
  const users = useQuery({
    queryKey: ["admin", "users"],
    queryFn: adminApi.users,
    enabled: areas.users,
  });
  const groups = useQuery({
    queryKey: ["admin", "groups"],
    queryFn: adminApi.groups,
    enabled: areas.groups,
  });
  const collections = useQuery({
    queryKey: ["admin", "collections"],
    queryFn: adminApi.collections,
    enabled: areas.collections,
  });
  const audit = useQuery({
    queryKey: ["audit", "status"],
    queryFn: adminApi.auditStatus,
    enabled: areas.audit,
    // Checking the chain reads the whole log: not on every visit.
    staleTime: 5 * 60 * 1000,
  });
  const number = new Intl.NumberFormat(getLocale());
  const count = (value: number) => number.format(value);
  // "%67" in Turkish, "67%" in English.
  const percent = new Intl.NumberFormat(getLocale(), { style: "percent" });

  const accounts = users.data ?? [];
  const active = accounts.filter((account) => account.status === "active").length;
  const withMfa = accounts.filter((account) => account.has_mfa).length;

  return (
    <AdminPage>
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">{m.admin_overview()}</h2>
        <p className="mt-0.5 text-sm text-muted-foreground">{m.admin_overview_lead()}</p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {areas.users && (
          <Tile
            to="/admin/users"
            icon={UserListIcon}
            label={m.nav_admin_users()}
            place={0}
            value={users.data === undefined ? null : accounts.length}
            detail={m.admin_stat_users_detail({
              active: count(active),
              disabled: count(accounts.length - active),
            })}
          />
        )}
        {areas.users && (
          <Tile
            to="/admin/users"
            icon={ShieldCheckIcon}
            label={m.admin_field_mfa()}
            place={1}
            value={
              users.data === undefined || accounts.length === 0
                ? null
                : Math.round((withMfa / accounts.length) * 100)
            }
            format={(n) => percent.format(n / 100)}
            detail={m.admin_stat_mfa_detail({
              with: count(withMfa),
              total: count(accounts.length),
            })}
          >
            <Meter share={accounts.length === 0 ? 0 : withMfa / accounts.length} />
          </Tile>
        )}
        {areas.groups && (
          <Tile
            to="/admin/groups"
            icon={UsersThreeIcon}
            label={m.nav_admin_groups()}
            place={2}
            value={groups.data === undefined ? null : groups.data.length}
            detail={m.admin_stat_groups_detail({
              members: count((groups.data ?? []).reduce((sum, g) => sum + g.member_count, 0)),
            })}
          />
        )}
        {areas.collections && (
          <Tile
            to="/admin/collections"
            icon={TreeStructureIcon}
            label={m.nav_admin_collections()}
            place={3}
            value={collections.data === undefined ? null : collections.data.length}
            detail={m.admin_stat_collections_detail({
              top: count((collections.data ?? []).filter((c) => c.parent_id === null).length),
            })}
          />
        )}
      </div>

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        {areas.users && users.data !== undefined && <Roles accounts={accounts} count={count} />}
        {(areas.users || areas.groups) && (
          <Attention accounts={users.data} groups={groups.data} count={count} />
        )}
        {areas.audit && (
          <Card title={m.admin_audit()}>
            {audit.data === undefined ? (
              <p className="text-sm text-muted-foreground">{m.common_loading()}</p>
            ) : audit.data.ok ? (
              <Status icon={CheckCircleIcon} tone="text-success">
                {m.admin_audit_ok({ count: count(audit.data.events_checked) })}
              </Status>
            ) : (
              <Status icon={WarningIcon} tone="text-destructive">
                {m.admin_audit_broken({ problem: audit.data.problem ?? "" })}
              </Status>
            )}
          </Card>
        )}
      </div>

      {(areas.users || areas.groups || areas.collections) && (
        <section>
          <h3 className="mb-2 text-xs font-medium text-muted-foreground">{m.admin_quick()}</h3>
          <div className="flex flex-wrap gap-2">
            {areas.users && (
              <QuickLink to="/admin/users" icon={UserPlusIcon} label={m.admin_quick_user()} />
            )}
            {areas.groups && (
              <QuickLink to="/admin/groups" icon={UsersThreeIcon} label={m.admin_quick_group()} />
            )}
            {areas.collections && (
              <QuickLink
                to="/admin/collections"
                icon={FolderPlusIcon}
                label={m.admin_quick_collection()}
              />
            )}
          </div>
        </section>
      )}
    </AdminPage>
  );
}

function Tile({
  to,
  icon: IconFor,
  label,
  place,
  value,
  format,
  detail,
  children,
}: {
  to: AreaPath;
  icon: Icon;
  label: string;
  // Its place in the row, for the entrance one after another.
  place: number;
  // Null while loading.
  value: number | null;
  format?: (value: number) => string;
  detail: string;
  children?: ReactNode;
}) {
  return (
    <SpotlightCard
      className="lift animate-rise rounded-2xl border bg-card shadow-raised"
      style={{ "--i": place } as CSSProperties}
    >
      <Link
        to={to}
        className="group flex h-full flex-col gap-1.5 rounded-2xl p-4 outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="flex items-center gap-2.5 text-sm font-medium text-subtle-foreground">
          <span className="flex size-8 items-center justify-center rounded-lg bg-secondary text-secondary-foreground transition-transform duration-300 group-hover:scale-110 group-hover:-rotate-6">
            <IconFor weight="duotone" className="size-[18px]" aria-hidden="true" />
          </span>
          {label}
        </span>
        <span className="mt-1 text-[30px] leading-tight font-semibold tracking-tight">
          {value === null ? (
            <span className="inline-block h-8 w-14 animate-pulse rounded-md bg-muted" />
          ) : (
            <CountUp to={value} {...(format === undefined ? {} : { format })} />
          )}
        </span>
        <span className="text-xs text-muted-foreground">{detail}</span>
        {children}
      </Link>
    </SpotlightCard>
  );
}

/** A share as a bar: the action colour on a lighter step of it. */
function Meter({ share }: { share: number }) {
  return (
    <span aria-hidden="true" className="mt-2 block h-1.5 overflow-hidden rounded-full bg-secondary">
      <span
        className="block h-full animate-grow rounded-full bg-primary transition-[width] duration-700 ease-out-soft"
        style={{ width: `${String(Math.round(share * 100))}%` }}
      />
    </span>
  );
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex animate-rise flex-col gap-3 rounded-2xl border bg-card p-5 shadow-raised [--i:4]">
      <h3 className="text-[15px] font-semibold">{title}</h3>
      {children}
    </section>
  );
}

/** How many accounts each role has, each with a bar for its share. */
function Roles({ accounts, count }: { accounts: Account[]; count: (n: number) => string }) {
  const most = Math.max(1, ...ROLES.map((role) => accounts.filter((a) => a.role === role).length));
  return (
    <Card title={m.admin_roles()}>
      <ul className="flex flex-col gap-2.5">
        {ROLES.map((role) => {
          const n = accounts.filter((account) => account.role === role).length;
          return (
            <li
              key={role}
              className="grid grid-cols-[6.5rem_minmax(0,1fr)_2rem] items-center gap-3"
            >
              <span className="truncate text-sm text-subtle-foreground">{roleLabel[role]()}</span>
              <span className="block h-2 overflow-hidden rounded-full bg-muted">
                <span
                  className="block h-full animate-grow rounded-full bg-primary/80 transition-[width] duration-700 ease-out-soft"
                  style={{ width: `${String((n / most) * 100)}%` }}
                />
              </span>
              <span className="text-right text-sm font-medium tabular-nums">{count(n)}</span>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

/** Accounts without a second factor, disabled accounts, groups nobody is in. */
function Attention({
  accounts,
  groups,
  count,
}: {
  accounts: Account[] | undefined;
  groups: Group[] | undefined;
  count: (n: number) => string;
}) {
  const items: { to: AreaPath; text: string; icon: Icon; tone: string }[] = [];
  const noMfa = (accounts ?? []).filter((a) => a.status === "active" && !a.has_mfa).length;
  const disabled = (accounts ?? []).filter((a) => a.status === "disabled").length;
  const empty = (groups ?? []).filter((g) => g.member_count === 0).length;
  if (noMfa > 0) {
    items.push({
      to: "/admin/users",
      text: m.admin_attention_mfa({ count: count(noMfa) }),
      icon: ShieldWarningIcon,
      tone: "text-warning",
    });
  }
  if (disabled > 0) {
    items.push({
      to: "/admin/users",
      text: m.admin_attention_disabled({ count: count(disabled) }),
      icon: WarningIcon,
      tone: "text-muted-foreground",
    });
  }
  if (empty > 0) {
    items.push({
      to: "/admin/groups",
      text: m.admin_attention_empty_groups({ count: count(empty) }),
      icon: UsersThreeIcon,
      tone: "text-muted-foreground",
    });
  }
  return (
    <Card title={m.admin_attention()}>
      {items.length === 0 ? (
        <Status icon={CheckCircleIcon} tone="text-success">
          {m.admin_attention_none()}
        </Status>
      ) : (
        <ul className="-mx-2 flex flex-col">
          {items.map((item) => (
            <li key={item.text}>
              <Link
                to={item.to}
                className="flex items-center gap-2.5 rounded-lg px-2 py-2 text-sm transition-colors hover:bg-accent"
              >
                <item.icon className={cn("size-4 shrink-0", item.tone)} aria-hidden="true" />
                {item.text}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Status({
  icon: IconFor,
  tone,
  children,
}: {
  icon: Icon;
  tone: string;
  children: ReactNode;
}) {
  return (
    <p className="flex items-center gap-2 text-sm">
      <IconFor weight="fill" className={cn("size-4 shrink-0", tone)} aria-hidden="true" />
      {children}
    </p>
  );
}

function QuickLink({ to, icon: IconFor, label }: { to: AreaPath; icon: Icon; label: string }) {
  return (
    <Link
      to={to}
      className="lift inline-flex h-10 items-center gap-2 rounded-xl border border-input bg-card px-3.5 text-sm font-medium shadow-raised"
    >
      <IconFor className="size-4 text-secondary-foreground" aria-hidden="true" />
      {label}
    </Link>
  );
}
