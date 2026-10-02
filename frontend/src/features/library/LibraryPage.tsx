import { BooksIcon, CaretRightIcon, FolderSimpleIcon, LockSimpleIcon } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Page } from "@/components/AppShell";
import { NativeSelect } from "@/components/NativeSelect";
import { inTreeOrder } from "@/features/admin/CollectionsPage";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";

import { DocumentTable } from "./DocumentTable";
import { libraryApi, type LibraryCollection } from "./libraryApi";
import { UploadBox } from "./UploadBox";

// Tailwind needs literal class names; deeper levels share the last one.
const INDENT = ["pl-2.5", "pl-6", "pl-9", "pl-12", "pl-15"];

/** The collections the user can read, as a tree beside the documents of the chosen one. */
export function LibraryPage() {
  const collections = useQuery({
    queryKey: ["library", "collections"],
    queryFn: libraryApi.collections,
  });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const tree = inTreeOrder(collections.data ?? []);
  // The first collection is open until the user picks another.
  const selected =
    collections.data?.find((collection) => collection.id === selectedId) ??
    tree[0]?.collection ??
    null;

  return (
    <Page
      title={selected?.name ?? m.nav_library()}
      wide
      crumb={
        selected !== null && (
          <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <BooksIcon className="size-4" aria-hidden="true" />
            <span className="hidden sm:inline">{m.nav_library()}</span>
            <CaretRightIcon className="size-3" aria-hidden="true" />
          </span>
        )
      }
    >
      <div className="flex min-h-0 flex-1">
        <nav
          aria-label={m.library_collections()}
          className="hidden w-64 shrink-0 overflow-y-auto border-r p-3 md:block"
        >
          <h2 className="px-2.5 pt-1 pb-1.5 text-xs font-medium text-muted-foreground">
            {m.library_collections()}
          </h2>
          <ul className="flex flex-col gap-px">
            {tree.map(({ collection, depth }) => {
              const current = collection.id === selected?.id;
              return (
                <li key={collection.id}>
                  <button
                    type="button"
                    aria-current={current ? "true" : undefined}
                    className={cn(
                      "flex h-10 w-full items-center gap-2.5 rounded-xl pr-2.5 text-left text-[14.5px] text-subtle-foreground transition-colors hover:bg-accent hover:text-foreground",
                      INDENT[Math.min(depth, INDENT.length - 1)],
                      current &&
                        "bg-secondary font-medium text-secondary-foreground hover:bg-secondary",
                    )}
                    onClick={() => {
                      setSelectedId(collection.id);
                    }}
                  >
                    <FolderSimpleIcon
                      weight={current ? "fill" : "regular"}
                      className="size-[18px] shrink-0"
                      aria-hidden="true"
                    />
                    <span className="min-w-0 flex-1 truncate">{collection.name}</span>
                    {!collection.can_write && (
                      <LockSimpleIcon className="size-3.5 shrink-0 opacity-60" aria-hidden="true" />
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 px-4 py-6 sm:px-8">
            {tree.length > 0 && (
              <label className="flex flex-col gap-1.5 text-sm md:hidden">
                <span className="text-xs font-medium text-muted-foreground">
                  {m.library_collection_label()}
                </span>
                <NativeSelect
                  value={selected?.id ?? ""}
                  onChange={(event) => {
                    setSelectedId(event.target.value);
                  }}
                >
                  {tree.map(({ collection, depth }) => (
                    <option key={collection.id} value={collection.id}>
                      {" ".repeat(depth)}
                      {collection.name}
                    </option>
                  ))}
                </NativeSelect>
              </label>
            )}
            {collections.data === undefined ? (
              <p className="text-sm text-muted-foreground">{m.common_loading()}</p>
            ) : selected === null ? (
              <Empty />
            ) : (
              <CollectionView key={selected.id} collection={selected} />
            )}
          </div>
        </div>
      </div>
    </Page>
  );
}

function Empty() {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed px-6 py-16 text-center">
      <BooksIcon weight="duotone" className="size-9 text-muted-foreground" aria-hidden="true" />
      <p className="max-w-sm text-sm text-muted-foreground">{m.library_no_collections()}</p>
    </div>
  );
}

function CollectionView({ collection }: { collection: LibraryCollection }) {
  return (
    <>
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">{collection.name}</h2>
        {collection.can_write && (
          <p className="mt-0.5 text-sm text-muted-foreground">{m.library_can_write()}</p>
        )}
      </header>
      {collection.can_write ? (
        <UploadBox collectionId={collection.id} />
      ) : (
        <p className="flex items-center gap-2 rounded-lg bg-muted px-3 py-2.5 text-sm text-subtle-foreground">
          <LockSimpleIcon className="size-4 shrink-0" aria-hidden="true" />
          {m.library_read_only()}
        </p>
      )}
      <DocumentTable collection={collection} />
    </>
  );
}
