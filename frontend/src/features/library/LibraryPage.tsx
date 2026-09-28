import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { AppShell } from "@/components/AppShell";
import { inTreeOrder } from "@/features/admin/CollectionsPage";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";

import { DocumentTable } from "./DocumentTable";
import { libraryApi, type LibraryCollection } from "./libraryApi";
import { UploadBox } from "./UploadBox";

export function LibraryPage() {
  const collections = useQuery({
    queryKey: ["library", "collections"],
    queryFn: libraryApi.collections,
  });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const tree = inTreeOrder(collections.data ?? []);
  const selected = collections.data?.find((collection) => collection.id === selectedId) ?? null;

  return (
    <AppShell>
      <h1 className="text-2xl font-semibold">{m.nav_library()}</h1>
      {collections.data === undefined ? (
        <p className="text-sm text-muted-foreground">{m.common_loading()}</p>
      ) : collections.data.length === 0 ? (
        <p className="text-sm text-muted-foreground">{m.library_no_collections()}</p>
      ) : (
        <div className="grid gap-4 md:grid-cols-[16rem_1fr]">
          <nav aria-label={m.library_collections()} className="rounded-lg border p-2">
            <ul className="flex flex-col">
              {tree.map(({ collection, depth }) => (
                <li key={collection.id}>
                  <button
                    type="button"
                    aria-current={collection.id === selectedId ? "true" : undefined}
                    className={cn(
                      "w-full rounded px-2 py-1 text-left text-sm hover:bg-muted",
                      collection.id === selectedId && "bg-muted font-medium",
                    )}
                    onClick={() => {
                      setSelectedId(collection.id);
                    }}
                  >
                    <span className={indent[Math.min(depth, indent.length - 1)]}>
                      {collection.name}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </nav>
          <section className="flex flex-col gap-4">
            {selected === null ? (
              <p className="text-sm text-muted-foreground">{m.library_pick_collection()}</p>
            ) : (
              <CollectionView collection={selected} />
            )}
          </section>
        </div>
      )}
    </AppShell>
  );
}

// Tailwind needs literal class names; deeper levels share the last one.
const indent = ["", "pl-3", "pl-6", "pl-9", "pl-12"];

function CollectionView({ collection }: { collection: LibraryCollection }) {
  return (
    <>
      <h2 className="text-lg font-medium">{collection.name}</h2>
      {collection.can_write ? (
        <UploadBox collectionId={collection.id} />
      ) : (
        <p className="text-sm text-muted-foreground">{m.library_read_only()}</p>
      )}
      <DocumentTable collection={collection} />
    </>
  );
}
