import {
  BooksIcon,
  CaretRightIcon,
  ChatsCircleIcon,
  FolderOpenIcon,
  FolderSimpleIcon,
  LockSimpleIcon,
} from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { AnimatePresence } from "motion/react";
import { useState } from "react";

import { Page } from "@/components/AppShell";
import { NativeSelect } from "@/components/NativeSelect";
import { buttonVariants } from "@/components/ui/button";
import { inTreeOrder } from "@/features/admin/CollectionsPage";
import { DocumentViewer, type Viewed } from "@/features/chat/DocumentViewer";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";

import { DocumentTable } from "./DocumentTable";
import { libraryApi, type LibraryCollection, type LibraryDocument } from "./libraryApi";
import { UploadBox } from "./UploadBox";

// Tailwind needs literal class names; deeper levels share the last one.
const INDENT = ["pl-2.5", "pl-6", "pl-9", "pl-12", "pl-15"];

/** The folders (collections) the user can read, as a tree beside the documents of the chosen
 * one; a document opens in the viewer beside the list. */
export function LibraryPage() {
  const collections = useQuery({
    queryKey: ["library", "collections"],
    queryFn: libraryApi.collections,
  });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [viewing, setViewing] = useState<Viewed | null>(null);
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
      panel={
        <AnimatePresence>
          {viewing !== null && (
            <DocumentViewer
              key={viewing.document_id}
              source={viewing}
              onClose={() => {
                setViewing(null);
              }}
            />
          )}
        </AnimatePresence>
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
                    title={collection.can_write ? undefined : m.library_view_only()}
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
              <CollectionView
                key={selected.id}
                collection={selected}
                onOpen={(document) => {
                  setViewing(opened(document));
                }}
              />
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

/** A document as the viewer opens it from the list: its first page, nothing marked. */
function opened(document: LibraryDocument): Viewed {
  return {
    document_id: document.id,
    title: document.title,
    version: document.latest_version,
    ordinal: null,
    page_start: 1,
    page_end: 1,
  };
}

function CollectionView({
  collection,
  onOpen,
}: {
  collection: LibraryCollection;
  onOpen: (document: LibraryDocument) => void;
}) {
  return (
    <>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2.5 text-2xl font-semibold tracking-tight">
            <FolderOpenIcon
              weight="duotone"
              className="size-7 shrink-0 text-secondary-foreground"
              aria-hidden="true"
            />
            <span className="min-w-0 truncate">{collection.name}</span>
          </h2>
          {collection.can_write && (
            <p className="mt-1 text-sm text-muted-foreground">{m.library_can_write()}</p>
          )}
        </div>
        <Link to="/" search={{}} className={buttonVariants({ variant: "outline" })}>
          <ChatsCircleIcon aria-hidden="true" />
          {m.library_ask()}
        </Link>
      </header>
      {collection.can_write ? (
        <UploadBox collectionId={collection.id} />
      ) : (
        <p className="flex items-center gap-2 rounded-lg bg-muted px-3 py-2.5 text-sm text-subtle-foreground">
          <LockSimpleIcon className="size-4 shrink-0" aria-hidden="true" />
          {m.library_read_only()}
        </p>
      )}
      <DocumentTable collection={collection} onOpen={onOpen} />
    </>
  );
}
