import { ArrowClockwiseIcon, CheckCircleIcon, WarningIcon } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";
import { getLocale } from "@/paraglide/runtime.js";

import { AdminPage } from "./AdminFrame";
import { adminApi, type Operations } from "./adminApi";
import { count, issuesOf, QUERY_KEY, type Issue } from "./system";
import { AuditLog, Backups, Documents, Parts, ScannedPages, Space } from "./SystemCards";

// The page is looked at, not watched: a minute is fresh enough, and "check again" is there.
const REFRESH_MS = 60_000;

export function SystemPage() {
  const operations = useQuery({
    queryKey: QUERY_KEY,
    queryFn: adminApi.operations,
    refetchInterval: REFRESH_MS,
  });

  return (
    <AdminPage
      actions={
        <Button
          variant="outline"
          onClick={() => void operations.refetch()}
          disabled={operations.isFetching}
        >
          <ArrowClockwiseIcon
            className={cn(operations.isFetching && "animate-spin")}
            aria-hidden="true"
          />
          {m.system_refresh()}
        </Button>
      }
    >
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">{m.system_title()}</h2>
        <p className="mt-0.5 text-sm text-muted-foreground">{m.system_lead()}</p>
      </header>
      {operations.data === undefined ? (
        <p className="text-sm text-muted-foreground">
          {operations.isError ? m.system_unavailable() : m.common_loading()}
        </p>
      ) : (
        <Overview operations={operations.data} checked={new Date(operations.dataUpdatedAt)} />
      )}
    </AdminPage>
  );
}

function Overview({ operations, checked }: { operations: Operations; checked: Date }) {
  const now = new Date();
  const issues = issuesOf(operations, now);
  return (
    <>
      <Summary issues={issues} checked={checked} />
      <div className="grid gap-3 lg:grid-cols-2">
        <Parts operations={operations} />
        <Documents operations={operations} />
        <ScannedPages operations={operations} />
        <Backups operations={operations} now={now} />
        <Space operations={operations} />
        <AuditLog operations={operations} now={now} />
      </div>
    </>
  );
}

function Summary({ issues, checked }: { issues: Issue[]; checked: Date }) {
  const time = new Intl.DateTimeFormat(getLocale(), { hour: "2-digit", minute: "2-digit" }).format(
    checked,
  );
  if (issues.length === 0) {
    return (
      <section className="flex animate-rise items-start gap-3.5 rounded-2xl border bg-card p-5 shadow-raised">
        <CheckCircleIcon
          weight="fill"
          className="size-7 shrink-0 text-success"
          aria-hidden="true"
        />
        <div>
          <h3 className="text-base font-semibold">{m.system_all_good()}</h3>
          <p className="mt-0.5 text-sm text-subtle-foreground">
            {m.system_all_good_detail()} {m.system_checked({ time })}
          </p>
        </div>
      </section>
    );
  }
  const serious = issues.some((issue) => issue.serious);
  return (
    <section
      className={cn(
        "flex animate-rise items-start gap-3.5 rounded-2xl border p-5 shadow-raised",
        serious ? "border-destructive/40 bg-destructive/5" : "border-warning/50 bg-warning/10",
      )}
    >
      <WarningIcon
        weight="fill"
        className={cn("size-7 shrink-0", serious ? "text-destructive" : "text-warning")}
        aria-hidden="true"
      />
      <div className="min-w-0">
        <h3 className="text-base font-semibold">
          {m.system_attention({ count: count(issues.length) })}
        </h3>
        <ul className="mt-2.5 flex flex-col gap-2">
          {issues.map((issue) => (
            <li key={issue.key} className="flex items-start gap-2.5 text-sm">
              <issue.icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <p>
                <strong className="font-semibold">{issue.title}</strong>{" "}
                <span className="text-subtle-foreground">{issue.what}</span>
              </p>
            </li>
          ))}
        </ul>
        <p className="mt-2.5 text-xs text-muted-foreground">{m.system_checked({ time })}</p>
      </div>
    </section>
  );
}
