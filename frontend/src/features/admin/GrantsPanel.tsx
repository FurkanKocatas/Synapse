import { useQuery } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";

import { FormError } from "@/components/AuthLayout";
import { NativeSelect } from "@/components/NativeSelect";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { fieldText } from "@/lib/forms";
import { m } from "@/paraglide/messages.js";

import {
  adminApi,
  PERMISSIONS,
  ROLES,
  type Collection,
  type Grant,
  type Permission,
  type PrincipalType,
  type Role,
} from "./adminApi";
import { permissionLabel, principalLabel, roleLabel } from "./labels";
import { useAction } from "@/lib/useAction";

const PRINCIPAL_TYPES: readonly PrincipalType[] = ["group", "user", "role"];

/** Who may read, write or manage one collection, and changes to that. */
export function GrantsPanel({ collection }: { collection: Collection }) {
  const grantsKey = ["admin", "collections", collection.id, "grants"];
  const grants = useQuery({ queryKey: grantsKey, queryFn: () => adminApi.grants(collection.id) });
  const users = useQuery({ queryKey: ["admin", "users"], queryFn: adminApi.users });
  const groups = useQuery({ queryKey: ["admin", "groups"], queryFn: adminApi.groups });
  const [principalType, setPrincipalType] = useState<PrincipalType>("group");
  const { run, error, busy } = useAction();

  const options: { value: string; label: string }[] =
    principalType === "user"
      ? (users.data ?? []).map((user) => ({ value: user.id, label: user.display_name }))
      : principalType === "group"
        ? (groups.data ?? []).map((group) => ({ value: group.id, label: group.name }))
        : ROLES.map((role) => ({ value: role, label: roleLabel[role]() }));

  function principalName(grant: Grant): string {
    if (grant.principal_type === "role") return roleLabel[grant.principal as Role]();
    const found =
      grant.principal_type === "user"
        ? users.data?.find((user) => user.id === grant.principal)?.display_name
        : groups.data?.find((group) => group.id === grant.principal)?.name;
    return found ?? grant.principal;
  }

  async function add(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const principal = fieldText(form, "principal");
    if (!principal) return;
    await run(
      () =>
        adminApi.addGrant(collection.id, {
          principal_type: principalType,
          principal,
          permission: fieldText(form, "permission") as Permission,
        }),
      [grantsKey],
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <h2 className="font-medium">{m.admin_grants_title({ name: collection.name })}</h2>
      <FormError message={error} />
      {grants.data?.length === 0 ? (
        <p className="text-sm text-muted-foreground">{m.admin_grants_empty()}</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {(grants.data ?? []).map((grant) => (
            <li key={grant.id} className="flex items-center justify-between text-sm">
              <span>
                {principalLabel[grant.principal_type]()}: {principalName(grant)} ·{" "}
                {permissionLabel[grant.permission]()}
              </span>
              <Button
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() => void run(() => adminApi.removeGrant(grant.id), [grantsKey])}
              >
                {m.common_remove()}
              </Button>
            </li>
          ))}
        </ul>
      )}
      <form className="grid gap-2 sm:grid-cols-3" onSubmit={(event) => void add(event)}>
        <div className="flex flex-col gap-1">
          <Label htmlFor="grant-type">{m.admin_grant_principal_type()}</Label>
          <NativeSelect
            id="grant-type"
            value={principalType}
            onChange={(event) => {
              setPrincipalType(event.target.value as PrincipalType);
            }}
          >
            {PRINCIPAL_TYPES.map((type) => (
              <option key={type} value={type}>
                {principalLabel[type]()}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="grant-principal">{m.admin_grant_principal()}</Label>
          <NativeSelect id="grant-principal" name="principal" key={principalType} defaultValue="">
            <option value="" disabled>
              {principalLabel[principalType]()}
            </option>
            {options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="grant-permission">{m.admin_grant_permission()}</Label>
          <NativeSelect id="grant-permission" name="permission" defaultValue="read">
            {PERMISSIONS.map((permission) => (
              <option key={permission} value={permission}>
                {permissionLabel[permission]()}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="sm:col-span-3">
          <Button type="submit" disabled={busy}>
            {m.common_add()}
          </Button>
        </div>
      </form>
    </div>
  );
}
