// Typed calls for the knowledge base (see docs/design/knowledge-base.md).

import { apiRequest, apiUpload } from "@/lib/api";

export type VersionStatus =
  "queued" | "parsing" | "parsed" | "ocr" | "embedding" | "ready" | "failed";

export interface LibraryCollection {
  id: string;
  parent_id: string | null;
  name: string;
  can_write: boolean;
  // The documents directly in it the user may read.
  document_count?: number;
}

export interface LibraryDocument {
  id: string;
  collection_id: string;
  title: string;
  latest_version: number;
  status: VersionStatus;
  failure: string | null;
  media_type: string;
  size_bytes: number;
  updated_at: string;
  // Suggested from the document when it was read, or set by a person.
  kind?: string | null;
  document_date?: string | null;
  reference?: string | null;
  tags?: string[];
  // Which of kind, document_date and reference a person set; the others were suggested.
  set_by_hand?: string[];
}

/** What a person changes of a document's details; null clears a kind, date or number. */
export interface MetadataChange {
  title?: string;
  kind?: string | null;
  document_date?: string | null;
  reference?: string | null;
  tags?: string[];
}

export interface DocumentVersion {
  id: string;
  version: number;
  filename: string;
  status: VersionStatus;
  failure: string | null;
}

/** Statuses that change on their own, so the list is refreshed while any is shown. */
export const IN_PROGRESS: ReadonlySet<VersionStatus> = new Set([
  "queued",
  "parsing",
  "ocr",
  "embedding",
]);

export const libraryApi = {
  collections: () => apiRequest<LibraryCollection[]>("GET", "/api/collections"),
  documents: (collectionId: string) =>
    apiRequest<LibraryDocument[]>("GET", `/api/collections/${collectionId}/documents`),
  versions: (documentId: string) =>
    apiRequest<DocumentVersion[]>("GET", `/api/documents/${documentId}/versions`),
  upload: (collectionId: string, file: File) =>
    apiUpload<{ id: string }>(
      `/api/collections/${collectionId}/documents?filename=${encodeURIComponent(file.name)}`,
      file,
    ),
  remove: (documentId: string) => apiRequest<undefined>("DELETE", `/api/documents/${documentId}`),
  updateMetadata: (documentId: string, changes: MetadataChange) =>
    apiRequest<undefined>("PATCH", `/api/documents/${documentId}`, changes),
  fileUrl: (documentId: string, version: number) =>
    `/api/documents/${documentId}/versions/${String(version)}/file`,
};
