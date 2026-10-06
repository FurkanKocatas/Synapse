import { CheckIcon, LockSimpleIcon, ShieldCheckIcon } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { FormError } from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";
import { useAction } from "@/lib/useAction";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";

import { AdminPage } from "./AdminFrame";
import {
  adminApi,
  MFA_ROLES,
  SETTINGS_KEY,
  type MfaRole,
  type OrganizationSettings,
} from "./adminApi";
import { roleLabel } from "./labels";
import { SettingsCard } from "./SettingsCard";
import { SynonymsCard } from "./SynonymsCard";

// What each role does, in words a newcomer understands.
const ROLE_DETAIL: Record<MfaRole, () => string> = {
  editor: m.settings_role_editor_detail,
  member: m.settings_role_member_detail,
  auditor: m.settings_role_auditor_detail,
};

/** The organisation's settings, for administrators: who must sign in with a second step, and
 * the words searches take as meaning the same. */
export function SettingsPage() {
  const settings = useQuery({ queryKey: SETTINGS_KEY, queryFn: adminApi.settings });
  return (
    <AdminPage>
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">{m.settings_title()}</h2>
        <p className="mt-0.5 text-sm text-muted-foreground">{m.settings_lead()}</p>
      </header>
      {settings.data === undefined ? (
        <p className="text-sm text-muted-foreground">{m.common_loading()}</p>
      ) : (
        <div className="flex max-w-3xl flex-col gap-4">
          <MfaCard settings={settings.data} />
          <SynonymsCard settings={settings.data} />
        </div>
      )}
    </AdminPage>
  );
}

function MfaCard({ settings }: { settings: OrganizationSettings }) {
  const [roles, setRoles] = useState<MfaRole[]>(settings.mfa_required_roles);
  const [saved, setSaved] = useState(false);
  const { run, error, busy } = useAction();
  const changed =
    roles.length !== settings.mfa_required_roles.length ||
    roles.some((role) => !settings.mfa_required_roles.includes(role));

  async function save() {
    setSaved(false);
    const ok = await run(
      () => adminApi.changeSettings({ mfa_required_roles: roles }),
      [SETTINGS_KEY],
    );
    setSaved(ok);
  }

  return (
    <SettingsCard
      icon={ShieldCheckIcon}
      title={m.settings_mfa_title()}
      lead={m.settings_mfa_lead()}
    >
      <fieldset>
        <legend className="mb-2.5 text-sm font-medium">{m.settings_mfa_ask()}</legend>
        <div className="grid gap-2 sm:grid-cols-3">
          {MFA_ROLES.map((role) => {
            const on = roles.includes(role);
            return (
              <label
                key={role}
                className={cn(
                  "flex cursor-pointer items-start gap-2.5 rounded-xl border px-3 py-2.5 transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
                  on && "border-primary bg-secondary",
                )}
              >
                <input
                  type="checkbox"
                  checked={on}
                  onChange={() => {
                    setSaved(false);
                    setRoles(on ? roles.filter((r) => r !== role) : [...roles, role]);
                  }}
                  className="peer sr-only"
                />
                <span
                  aria-hidden="true"
                  className={cn(
                    "mt-0.5 inline-flex size-[17px] shrink-0 items-center justify-center rounded-[5px] border-[1.5px] border-input text-primary-foreground",
                    on && "border-primary bg-primary",
                  )}
                >
                  {on && <CheckIcon weight="bold" className="size-3" />}
                </span>
                <span>
                  <b className="block text-[13.5px] font-semibold">{roleLabel[role]()}</b>
                  <small className="text-xs text-muted-foreground">{ROLE_DETAIL[role]()}</small>
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>
      <p className="mt-2.5 flex items-start gap-2 text-[12.5px] text-muted-foreground">
        <LockSimpleIcon weight="fill" className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
        {m.settings_mfa_always()}
      </p>
      <FormError message={error} />
      <div className="mt-3 flex items-center justify-end gap-3">
        {saved && !changed && (
          <span role="status" className="text-sm text-muted-foreground">
            {m.settings_saved()}
          </span>
        )}
        <Button disabled={!changed || busy} onClick={() => void save()}>
          {m.chat_save()}
        </Button>
      </div>
    </SettingsCard>
  );
}
