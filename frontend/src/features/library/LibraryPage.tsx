import { useQuery } from "@tanstack/react-query";
import { Folder, FolderOpen, Lock } from "lucide-react";
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

  const pane = (
    <nav aria-label={m.library_collections()} className="flex flex-col gap-1 p-3">
      <h2 className="px-2 pt-1 pb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">
        {m.library_collections()}
      </h2>
      {collections.data === undefined ? (
        <p className="px-2 text-sm text-muted-foreground">{m.common_loading()}</p>
      ) : collections.data.length === 0 ? (
        <p className="px-2 text-sm text-muted-foreground">{m.library_no_collections()}</p>
      ) : (
        <ul className="flex flex-col gap-0.5">
          {tree.map(({ collection, depth }) => (
            <li key={collection.id}>
              <button
                type="button"
                aria-current={collection.id === selectedId ? "true" : undefined}
                className={cn(
                  "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-accent/60",
                  collection.id === selectedId && "bg-accent font-medium text-accent-foreground",
                )}
                onClick={() => {
                  setSelectedId(collection.id);
                }}
              >
                <span
                  className={cn(
                    "flex min-w-0 items-center gap-2",
                    indent[Math.min(depth, indent.length - 1)],
                  )}
                >
                  {collection.id === selectedId ? (
                    <FolderOpen className="size-4 shrink-0" aria-hidden="true" />
                  ) : (
                    <Folder className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                  )}
                  <span className="truncate">{collection.name}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </nav>
  );

  return (
    <AppShell
      title={selected?.name ?? m.nav_library()}
      icon={FolderOpen}
      pane={pane}
      paneLabel={m.library_collections()}
    >
      {selected === null ? (
        <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed bg-card px-6 py-16 text-center">
          <span className="flex size-12 items-center justify-center rounded-2xl bg-accent text-accent-foreground">
            <FolderOpen className="size-6" aria-hidden="true" />
          </span>
          <p className="max-w-sm text-sm text-muted-foreground">{m.library_pick_collection()}</p>
        </div>
      ) : (
        <CollectionView collection={selected} />
      )}
    </AppShell>
  );
}

// Tailwind needs literal class names; deeper levels share the last one.
const indent = ["", "pl-3", "pl-6", "pl-9", "pl-12"];

function CollectionView({ collection }: { collection: LibraryCollection }) {
  return (
    <>
      {collection.can_write ? (
        <UploadBox collectionId={collection.id} />
      ) : (
        <p className="flex items-center gap-2 rounded-xl border bg-card px-4 py-3 text-sm text-muted-foreground">
          <Lock className="size-4" aria-hidden="true" />
          {m.library_read_only()}
        </p>
      )}
      <DocumentTable collection={collection} />
    </>
  );
}
