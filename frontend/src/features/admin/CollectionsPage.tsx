import { useQuery, useSuspenseQuery } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";

import { AppShell } from "@/components/AppShell";
import { FormError } from "@/components/AuthLayout";
import { NativeSelect } from "@/components/NativeSelect";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { sessionQuery } from "@/features/auth/session";
import { fieldText } from "@/lib/forms";
import { m } from "@/paraglide/messages.js";

import { adminApi, adminAreas, type Collection } from "./adminApi";
import { GrantsPanel } from "./GrantsPanel";
import { useAction } from "@/lib/useAction";

const COLLECTIONS = ["admin", "collections"];

/** Collections in tree order, each with its depth, so the list reads like folders. */
export function inTreeOrder(
  collections: Collection[],
): { collection: Collection; depth: number }[] {
  const children = new Map<string | null, Collection[]>();
  for (const collection of collections) {
    const siblings = children.get(collection.parent_id) ?? [];
    siblings.push(collection);
    children.set(collection.parent_id, siblings);
  }
  const ordered: { collection: Collection; depth: number }[] = [];
  const visit = (parent: string | null, depth: number) => {
    for (const collection of children.get(parent) ?? []) {
      ordered.push({ collection, depth });
      visit(collection.id, depth + 1);
    }
  };
  visit(null, 0);
  return ordered;
}

export function CollectionsPage() {
  const { data: session } = useSuspenseQuery(sessionQuery);
  const areas = adminAreas(session?.user?.role);
  const collections = useQuery({ queryKey: COLLECTIONS, queryFn: adminApi.collections });
  const [selected, setSelected] = useState<Collection | null>(null);
  const { run, error, busy } = useAction();
  const tree = inTreeOrder(collections.data ?? []);

  async function create(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const parent = fieldText(form, "parent");
    const created = await run(
      () => adminApi.createCollection(fieldText(form, "name"), parent || null),
      [COLLECTIONS],
    );
    if (created) form.reset();
  }

  return (
    <AppShell>
      <h1 className="text-2xl font-semibold">{m.nav_admin_collections()}</h1>
      <FormError message={error} />
      <div className="grid gap-4 md:grid-cols-2">
        <section className="flex flex-col gap-3 rounded-lg border p-4">
          <form className="grid gap-2" onSubmit={(event) => void create(event)}>
            <div className="flex flex-col gap-1">
              <Label htmlFor="collection-name">{m.admin_collection_name()}</Label>
              <Input id="collection-name" name="name" required maxLength={200} />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="collection-parent">{m.admin_collection_parent()}</Label>
              <NativeSelect id="collection-parent" name="parent" defaultValue="">
                <option value="">{m.admin_collection_top_level()}</option>
                {tree.map(({ collection, depth }) => (
                  <option key={collection.id} value={collection.id}>
                    {"  ".repeat(depth)}
                    {collection.name}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <div>
              <Button type="submit" disabled={busy}>
                {m.common_create()}
              </Button>
            </div>
          </form>
          <ul className="flex flex-col gap-1">
            {tree.map(({ collection, depth }) => (
              <li key={collection.id}>
                <button
                  type="button"
                  aria-pressed={selected?.id === collection.id}
                  className="w-full rounded px-2 py-1 text-left text-sm hover:bg-muted aria-pressed:bg-muted"
                  style={{ paddingLeft: `${String(0.5 + depth * 1.25)}rem` }}
                  onClick={() => {
                    setSelected(collection);
                  }}
                >
                  {collection.name}
                </button>
              </li>
            ))}
          </ul>
        </section>
        {areas.grants ? (
          <section className="rounded-lg border p-4">
            {selected === null ? (
              <p className="text-sm text-muted-foreground">{m.admin_collection_select()}</p>
            ) : (
              <GrantsPanel key={selected.id} collection={selected} />
            )}
          </section>
        ) : null}
      </div>
    </AppShell>
  );
}
