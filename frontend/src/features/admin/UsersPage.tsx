import { useQuery, useSuspenseQuery } from "@tanstack/react-query";
import { ShieldCheckIcon, ShieldWarningIcon } from "@phosphor-icons/react";
import { useState, type SubmitEvent } from "react";

import { FormError } from "@/components/AuthLayout";
import { NativeSelect } from "@/components/NativeSelect";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { sessionQuery } from "@/features/auth/session";
import { fieldText } from "@/lib/forms";
import { initials } from "@/lib/initials";
import { getLocale } from "@/paraglide/runtime.js";
import { m } from "@/paraglide/messages.js";

import { AdminPage } from "./AdminFrame";
import { adminApi, ROLES, type Account, type Role } from "./adminApi";
import { roleLabel } from "./labels";
import { ResetPanel } from "./ResetPanel";
import { useAction } from "@/lib/useAction";

const USERS = ["admin", "users"];

export function UsersPage() {
  const users = useQuery({ queryKey: USERS, queryFn: adminApi.users });
  const { data: session } = useSuspenseQuery(sessionQuery);
  const { run, error, busy } = useAction();
  const [resetting, setResetting] = useState<string | null>(null);
  const selected = users.data?.find((account) => account.id === resetting);

  async function create(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const created = await run(
      () =>
        adminApi.createUser({
          email: fieldText(form, "email"),
          display_name: fieldText(form, "display_name"),
          role: fieldText(form, "role") as Role,
          password: fieldText(form, "password"),
          locale: getLocale(),
        }),
      [USERS],
    );
    if (created) form.reset();
  }

  function change(account: Account, body: Parameters<typeof adminApi.changeUser>[1]) {
    void run(() => adminApi.changeUser(account.id, body), [USERS]);
  }

  return (
    <AdminPage>
      <h2 className="text-xl font-medium tracking-tight">{m.nav_admin_users()}</h2>
      <FormError message={error} />

      <form
        className="grid gap-3 rounded-xl border bg-card p-5 sm:grid-cols-2"
        onSubmit={(event) => void create(event)}
      >
        <h2 className="text-base font-medium sm:col-span-2">{m.admin_users_new()}</h2>
        <div className="flex flex-col gap-1">
          <Label htmlFor="new-name">{m.admin_field_display_name()}</Label>
          <Input id="new-name" name="display_name" required maxLength={200} />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="new-email">{m.admin_field_email()}</Label>
          <Input id="new-email" name="email" type="email" required autoComplete="off" />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="new-role">{m.admin_field_role()}</Label>
          <NativeSelect id="new-role" name="role" defaultValue="member">
            {ROLES.map((role) => (
              <option key={role} value={role}>
                {roleLabel[role]()}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="new-password">{m.admin_field_password()}</Label>
          <Input
            id="new-password"
            name="password"
            type="password"
            required
            minLength={15}
            autoComplete="new-password"
            aria-describedby="new-password-hint"
          />
          <span id="new-password-hint" className="text-xs text-muted-foreground">
            {m.admin_password_hint()}
          </span>
        </div>
        <div className="sm:col-span-2">
          <Button type="submit" disabled={busy}>
            {m.common_create()}
          </Button>
        </div>
      </form>

      {users.data === undefined ? (
        <p className="text-sm text-muted-foreground">{m.common_loading()}</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border bg-card">
          <table className="w-full text-sm">
            <thead className="border-b bg-sidebar text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-2 font-medium">{m.admin_field_display_name()}</th>
                <th className="px-3 py-2 font-medium">{m.admin_field_role()}</th>
                <th className="px-3 py-2 font-medium">{m.admin_field_status()}</th>
                <th className="px-3 py-2 font-medium">{m.admin_field_mfa()}</th>
                <th className="px-3 py-2 font-medium">{m.admin_field_actions()}</th>
              </tr>
            </thead>
            <tbody>
              {users.data.map((account) => (
                <tr key={account.id} className="border-t transition-colors hover:bg-background">
                  <td className="px-4 py-2.5">
                    <div className="flex min-w-48 items-center gap-3">
                      <span
                        aria-hidden="true"
                        className="flex size-8 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-semibold text-secondary-foreground"
                      >
                        {initials(account.display_name)}
                      </span>
                      <span className="min-w-0 leading-tight">
                        <span className="block truncate font-medium">{account.display_name}</span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {account.email}
                        </span>
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <NativeSelect
                      aria-label={`${m.admin_field_role()}: ${account.display_name}`}
                      value={account.role}
                      disabled={busy}
                      onChange={(event) => {
                        change(account, { role: event.target.value as Role });
                      }}
                    >
                      {ROLES.map((role) => (
                        <option key={role} value={role}>
                          {roleLabel[role]()}
                        </option>
                      ))}
                    </NativeSelect>
                  </td>
                  <td className="px-3 py-2">
                    <NativeSelect
                      aria-label={`${m.admin_field_status()}: ${account.display_name}`}
                      value={account.status}
                      disabled={busy}
                      onChange={(event) => {
                        change(account, { status: event.target.value as Account["status"] });
                      }}
                    >
                      <option value="active">{m.status_active()}</option>
                      <option value="disabled">{m.status_disabled()}</option>
                    </NativeSelect>
                  </td>
                  <td className="px-3 py-2">
                    {account.has_mfa ? (
                      <span className="inline-flex items-center gap-1.5 text-[13px]">
                        <ShieldCheckIcon
                          weight="fill"
                          className="size-4 text-success"
                          aria-hidden="true"
                        />
                        {m.mfa_on()}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 text-[13px] text-subtle-foreground">
                        <ShieldWarningIcon
                          weight="fill"
                          className="size-4 text-warning"
                          aria-hidden="true"
                        />
                        {m.mfa_off()}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {account.id !== session?.user?.id && (
                      <Button
                        variant="outline"
                        size="sm"
                        aria-pressed={resetting === account.id}
                        onClick={() => {
                          setResetting(account.id);
                        }}
                      >
                        {m.admin_reset_open()}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && <ResetPanel key={selected.id} account={selected} refresh={[USERS]} />}
    </AdminPage>
  );
}
