// Typed calls for /api/admin (see docs/design/authorization.md).

import type { User } from "@/features/auth/authApi";
import { apiRequest } from "@/lib/api";

export type Role = User["role"];
export type Permission = "read" | "write" | "manage";
export type PrincipalType = "user" | "group" | "role";

export const ROLES: readonly Role[] = ["admin", "editor", "member", "auditor"];
export const PERMISSIONS: readonly Permission[] = ["read", "write", "manage"];

export interface Account {
  id: string;
  email: string;
  display_name: string;
  role: Role;
  status: "active" | "disabled";
  locale: string;
  has_mfa: boolean;
}

export interface Group {
  id: string;
  name: string;
  member_count: number;
}

export interface Member {
  user_id: string;
  display_name: string;
  email: string;
}

export interface Collection {
  id: string;
  parent_id: string | null;
  name: string;
}

export interface Grant {
  id: string;
  collection_id: string;
  principal_type: PrincipalType;
  principal: string;
  permission: Permission;
}

export interface AuditStatus {
  ok: boolean;
  events_checked: number;
  problem: string | null;
}

export type RunKind = "backup" | "backup_verify" | "files_sweep" | "audit_verify";

export interface Run {
  kind: RunKind;
  ok: boolean;
  started_at: string;
  finished_at: string;
  details: Record<string, string | number | boolean | null>;
}

/** The operations page's figures (docs/design/operations.md). */
export interface Operations {
  services: { name: string; ok: boolean; connections: number | null }[];
  queues: { queue: string; waiting: number; running: number; failed: number }[];
  // Live documents by the status of their latest version.
  documents: Record<string, number>;
  deleted_waiting: number;
  retryable: number;
  pages: {
    total: number;
    read_by_ocr: number;
    waiting_for_ocr: number;
    not_read: number;
    with_uncertain_identifiers: number;
  };
  storage: {
    files_bytes: number;
    database_bytes: number;
    disk_free_bytes: number;
    disk_total_bytes: number;
  };
  runs: { latest: Partial<Record<RunKind, Run>>; latest_ok: Partial<Record<RunKind, Run>> };
  problems: Record<string, number>;
}

export interface Retried {
  reprocessing: number;
  embedding: number;
}

interface Created {
  id: string;
}

export const adminApi = {
  users: () => apiRequest<Account[]>("GET", "/api/admin/users"),
  createUser: (body: {
    email: string;
    display_name: string;
    role: Role;
    password: string;
    locale: string;
  }) => apiRequest<Created>("POST", "/api/admin/users", body),
  changeUser: (id: string, body: { role?: Role; status?: Account["status"] }) =>
    apiRequest<Account>("PATCH", `/api/admin/users/${id}`, body),
  resetPassword: (id: string, password: string) =>
    apiRequest<undefined>("POST", `/api/admin/users/${id}/password`, { password }),
  resetMfa: (id: string) => apiRequest<undefined>("DELETE", `/api/admin/users/${id}/mfa`),

  groups: () => apiRequest<Group[]>("GET", "/api/admin/groups"),
  createGroup: (name: string) => apiRequest<Created>("POST", "/api/admin/groups", { name }),
  members: (groupId: string) => apiRequest<Member[]>("GET", `/api/admin/groups/${groupId}/members`),
  addMember: (groupId: string, userId: string) =>
    apiRequest<undefined>("POST", `/api/admin/groups/${groupId}/members`, { user_id: userId }),
  removeMember: (groupId: string, userId: string) =>
    apiRequest<undefined>("DELETE", `/api/admin/groups/${groupId}/members/${userId}`),

  collections: () => apiRequest<Collection[]>("GET", "/api/admin/collections"),
  createCollection: (name: string, parentId: string | null) =>
    apiRequest<Created>("POST", "/api/admin/collections", { name, parent_id: parentId }),
  grants: (collectionId: string) =>
    apiRequest<Grant[]>("GET", `/api/admin/collections/${collectionId}/grants`),
  addGrant: (
    collectionId: string,
    body: { principal_type: PrincipalType; principal: string; permission: Permission },
  ) => apiRequest<Created>("POST", `/api/admin/collections/${collectionId}/grants`, body),
  removeGrant: (grantId: string) => apiRequest<undefined>("DELETE", `/api/admin/grants/${grantId}`),

  auditStatus: () => apiRequest<AuditStatus>("GET", "/api/audit/status"),

  operations: () => apiRequest<Operations>("GET", "/api/admin/operations"),
  retryProcessing: () => apiRequest<Retried>("POST", "/api/admin/operations/retry"),
};

/** What the signed-in role may see in the administration area (the server enforces it). */
export function adminAreas(role: Role | undefined) {
  return {
    users: role === "admin",
    groups: role === "admin",
    collections: role === "admin" || role === "editor",
    grants: role === "admin",
    audit: role === "auditor",
    operations: role === "admin",
  };
}

/** Whether the role has any part of the administration panel. */
export function hasAdministration(role: Role | undefined): boolean {
  return Object.values(adminAreas(role)).some(Boolean);
}
