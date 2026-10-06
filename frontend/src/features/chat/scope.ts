// Where a question is searched: everything the user may read, or the folders and documents they
// chose (backend/src/synapse/knowledge/scope.py). A chosen folder covers the folders inside it.

import { useQuery, useQueryClient, type Query, type QueryKey } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { libraryApi, type LibraryCollection } from "@/features/library/libraryApi";
import { m } from "@/paraglide/messages.js";

export interface ChatScope {
  collections: string[];
  documents: string[];
}

export const EVERYTHING: ChatScope = { collections: [], documents: [] };
// The server's limits (scope.py): beyond them a question is refused.
export const MAX_COLLECTIONS = 50;
export const MAX_DOCUMENTS = 200;

// Shared with the library page, so a folder's documents are fetched once.
export const COLLECTIONS_KEY = ["library", "collections"];
export function documentsKey(collectionId: string) {
  return ["library", "documents", collectionId];
}

export function isEverything(scope: ChatScope | null | undefined): boolean {
  return scope == null || (scope.collections.length === 0 && scope.documents.length === 0);
}

export function sameScope(a: ChatScope, b: ChatScope): boolean {
  const same = (x: string[], y: string[]) =>
    x.length === y.length && x.every((item) => y.includes(item));
  return same(a.collections, b.collections) && same(a.documents, b.documents);
}

/** A folder in the tree, with the folders inside it. */
export interface FolderNode {
  folder: LibraryCollection;
  depth: number;
  children: FolderNode[];
}

export function folderTree(folders: LibraryCollection[]): FolderNode[] {
  const known = new Set(folders.map((f) => f.id));
  const byParent = new Map<string | null, LibraryCollection[]>();
  for (const folder of folders) {
    // A folder whose parent the user cannot see stands at the top, as the library shows it.
    const parent =
      folder.parent_id !== null && known.has(folder.parent_id) ? folder.parent_id : null;
    byParent.set(parent, [...(byParent.get(parent) ?? []), folder]);
  }
  const build = (parent: string | null, depth: number): FolderNode[] =>
    (byParent.get(parent) ?? []).map((folder) => ({
      folder,
      depth,
      children: build(folder.id, depth + 1),
    }));
  return build(null, 0);
}

/** Each folder's parent, for walking up the tree. */
export function parents(folders: LibraryCollection[]): Map<string, string | null> {
  return new Map(folders.map((f) => [f.id, f.parent_id]));
}

/** Whether ``folderId`` is chosen, itself or through a folder it lies in. */
export function covered(scope: ChatScope, folderId: string, up: Map<string, string | null>) {
  for (let at: string | null | undefined = folderId; at != null; at = up.get(at)) {
    if (scope.collections.includes(at)) return true;
  }
  return false;
}

export type Mark = "on" | "inherited" | "part" | "off";

/** How a folder's box shows: chosen, chosen through a folder above it, partly chosen (a folder
 * or document inside it), or not. ``folderOf`` knows the folder of the documents seen so far. */
export function folderMark(
  scope: ChatScope,
  node: FolderNode,
  up: Map<string, string | null>,
  folderOf: Map<string, string>,
): Mark {
  if (scope.collections.includes(node.folder.id)) return "on";
  if (covered(scope, node.folder.id, up)) return "inherited";
  const inside = (n: FolderNode): boolean =>
    n.children.some((child) => scope.collections.includes(child.folder.id) || inside(child)) ||
    scope.documents.some((d) => folderOf.get(d) === n.folder.id);
  return inside(node) ? "part" : "off";
}

/** The scope with ``node`` chosen, and what lies inside it no longer chosen on its own; or, if
 * it was chosen, not. */
export function toggleFolder(
  scope: ChatScope,
  node: FolderNode,
  folderOf: Map<string, string>,
): ChatScope {
  const id = node.folder.id;
  if (scope.collections.includes(id)) {
    return { ...scope, collections: scope.collections.filter((c) => c !== id) };
  }
  const within = new Set<string>();
  const walk = (n: FolderNode) => {
    within.add(n.folder.id);
    n.children.forEach(walk);
  };
  walk(node);
  return {
    collections: [...scope.collections.filter((c) => !within.has(c)), id],
    documents: scope.documents.filter((d) => !within.has(folderOf.get(d) ?? "")),
  };
}

export function toggleDocument(scope: ChatScope, documentId: string): ChatScope {
  return scope.documents.includes(documentId)
    ? { ...scope, documents: scope.documents.filter((d) => d !== documentId) }
    : { ...scope, documents: [...scope.documents, documentId] };
}

/** The scope in a few words: "Mali İşler", "Mali İşler ve 1 belge", "3 klasör ve 2 belge". */
export function scopeLabel(
  scope: ChatScope,
  names: Map<string, string>,
  titles: Map<string, string>,
): string {
  if (isEverything(scope)) return m.chat_scope();
  const folders = scope.collections.map((id) => names.get(id) ?? m.chat_scope_folder_unknown());
  const documents = scope.documents.length;
  const first = folders[0];
  if (documents === 0 && first !== undefined) {
    if (folders.length === 1) return first;
    if (folders.length === 2) return m.chat_scope_and({ first, second: folders[1] ?? "" });
    return m.chat_scope_more_folders({ first, count: String(folders.length - 1) });
  }
  const title = titles.get(scope.documents[0] ?? "");
  const counted = m.chat_scope_documents({ count: String(documents) });
  if (first === undefined) return documents === 1 && title !== undefined ? title : counted;
  const folderPart =
    folders.length === 1 ? first : m.chat_scope_folders({ count: String(folders.length) });
  return m.chat_scope_and({ first: folderPart, second: counted });
}

/** The names the label needs: every folder the user can see, and the titles of the documents
 * of every folder whose list has been fetched. */
export function useScopeNames(): {
  folders: LibraryCollection[];
  names: Map<string, string>;
  titles: Map<string, string>;
  folderOf: Map<string, string>;
} {
  const collections = useQuery({ queryKey: COLLECTIONS_KEY, queryFn: libraryApi.collections });
  const client = useQueryClient();
  // Read again whenever a folder's documents arrive: the titles and folders come from them.
  const [, setSeen] = useState(0);
  useEffect(
    () =>
      client.getQueryCache().subscribe((event) => {
        const key: QueryKey = (event.query as Query).queryKey;
        if (event.type === "updated" && key[1] === "documents") setSeen((n) => n + 1);
      }),
    [client],
  );
  const folders = collections.data ?? [];
  const titles = new Map<string, string>();
  const folderOf = new Map<string, string>();
  for (const [key, documents] of client.getQueriesData<{ id: string; title: string }[]>({
    queryKey: ["library", "documents"],
  })) {
    const folder = key[2];
    for (const document of documents ?? []) {
      titles.set(document.id, document.title);
      if (typeof folder === "string") folderOf.set(document.id, folder);
    }
  }
  return { folders, names: new Map(folders.map((f) => [f.id, f.name])), titles, folderOf };
}
