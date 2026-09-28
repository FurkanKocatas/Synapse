import { useQuery } from "@tanstack/react-query";
import type { SubmitEvent } from "react";

import { AppShell } from "@/components/AppShell";
import { FormError } from "@/components/AuthLayout";
import { NativeSelect } from "@/components/NativeSelect";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fieldText } from "@/lib/forms";
import { getLocale } from "@/paraglide/runtime.js";
import { m } from "@/paraglide/messages.js";

import { adminApi, ROLES, type Account, type Role } from "./adminApi";
import { roleLabel } from "./labels";
import { useAdminAction } from "./useAdminAction";

const USERS = ["admin", "users"];

export function UsersPage() {
  const users = useQuery({ queryKey: USERS, queryFn: adminApi.users });
  const { run, error, busy } = useAdminAction();

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
    <AppShell>
      <h1 className="text-2xl font-semibold">{m.nav_admin_users()}</h1>
      <FormError message={error} />

      <form
        className="grid gap-3 rounded-lg border p-4 sm:grid-cols-2"
        onSubmit={(event) => void create(event)}
      >
        <h2 className="font-medium sm:col-span-2">{m.admin_users_new()}</h2>
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
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left">
              <tr>
                <th className="p-2">{m.admin_field_display_name()}</th>
                <th className="p-2">{m.admin_field_email()}</th>
                <th className="p-2">{m.admin_field_role()}</th>
                <th className="p-2">{m.admin_field_status()}</th>
                <th className="p-2">{m.admin_field_mfa()}</th>
              </tr>
            </thead>
            <tbody>
              {users.data.map((account) => (
                <tr key={account.id} className="border-t">
                  <td className="p-2">{account.display_name}</td>
                  <td className="p-2">{account.email}</td>
                  <td className="p-2">
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
                  <td className="p-2">
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
                  <td className="p-2">{account.has_mfa ? m.mfa_on() : m.mfa_off()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </AppShell>
  );
}
