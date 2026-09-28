import { useQuery } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";

import { AppShell } from "@/components/AppShell";
import { FormError } from "@/components/AuthLayout";
import { NativeSelect } from "@/components/NativeSelect";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fieldText } from "@/lib/forms";
import { m } from "@/paraglide/messages.js";

import { adminApi, type Group } from "./adminApi";
import { useAction } from "@/lib/useAction";

const GROUPS = ["admin", "groups"];

export function GroupsPage() {
  const groups = useQuery({ queryKey: GROUPS, queryFn: adminApi.groups });
  const [selected, setSelected] = useState<Group | null>(null);
  const { run, error, busy } = useAction();

  async function create(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    if (await run(() => adminApi.createGroup(fieldText(form, "name")), [GROUPS])) form.reset();
  }

  return (
    <AppShell>
      <h1 className="text-2xl font-semibold">{m.nav_admin_groups()}</h1>
      <FormError message={error} />
      <div className="grid gap-4 md:grid-cols-2">
        <section className="flex flex-col gap-3 rounded-lg border p-4">
          <form className="flex items-end gap-2" onSubmit={(event) => void create(event)}>
            <div className="flex flex-1 flex-col gap-1">
              <Label htmlFor="group-name">{m.admin_group_name()}</Label>
              <Input id="group-name" name="name" required maxLength={200} />
            </div>
            <Button type="submit" disabled={busy}>
              {m.common_create()}
            </Button>
          </form>
          <ul className="flex flex-col gap-1">
            {(groups.data ?? []).map((group) => (
              <li key={group.id}>
                <button
                  type="button"
                  aria-pressed={selected?.id === group.id}
                  className="flex w-full justify-between rounded px-2 py-1 text-left text-sm hover:bg-muted aria-pressed:bg-muted"
                  onClick={() => {
                    setSelected(group);
                  }}
                >
                  <span>{group.name}</span>
                  <span className="text-muted-foreground">{group.member_count}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
        <section className="rounded-lg border p-4">
          {selected === null ? (
            <p className="text-sm text-muted-foreground">{m.admin_group_select()}</p>
          ) : (
            <GroupMembers key={selected.id} group={selected} />
          )}
        </section>
      </div>
    </AppShell>
  );
}

function GroupMembers({ group }: { group: Group }) {
  const membersKey = ["admin", "groups", group.id, "members"];
  const members = useQuery({ queryKey: membersKey, queryFn: () => adminApi.members(group.id) });
  const users = useQuery({ queryKey: ["admin", "users"], queryFn: adminApi.users });
  const { run, error, busy } = useAction();
  const memberIds = new Set((members.data ?? []).map((member) => member.user_id));
  const candidates = (users.data ?? []).filter((user) => !memberIds.has(user.id));
  const refresh = [membersKey, GROUPS];

  async function add(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const userId = fieldText(event.currentTarget, "user");
    if (userId) await run(() => adminApi.addMember(group.id, userId), refresh);
  }

  return (
    <div className="flex flex-col gap-3">
      <h2 className="font-medium">
        {group.name}: {m.admin_group_members({ count: String(members.data?.length ?? 0) })}
      </h2>
      <FormError message={error} />
      <form className="flex items-end gap-2" onSubmit={(event) => void add(event)}>
        <div className="flex flex-1 flex-col gap-1">
          <Label htmlFor="member-user">{m.admin_group_add_member()}</Label>
          <NativeSelect id="member-user" name="user" defaultValue="">
            <option value="" disabled>
              {m.admin_choose_user()}
            </option>
            {candidates.map((user) => (
              <option key={user.id} value={user.id}>
                {user.display_name} ({user.email})
              </option>
            ))}
          </NativeSelect>
        </div>
        <Button type="submit" disabled={busy || candidates.length === 0}>
          {m.common_add()}
        </Button>
      </form>
      {members.data?.length === 0 ? (
        <p className="text-sm text-muted-foreground">{m.admin_group_no_members()}</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {(members.data ?? []).map((member) => (
            <li key={member.user_id} className="flex items-center justify-between text-sm">
              <span>
                {member.display_name} <span className="text-muted-foreground">{member.email}</span>
              </span>
              <Button
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() =>
                  void run(() => adminApi.removeMember(group.id, member.user_id), refresh)
                }
              >
                {m.common_remove()}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
