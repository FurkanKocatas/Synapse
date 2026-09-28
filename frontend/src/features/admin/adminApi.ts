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
};

/** What the signed-in role may see in the administration area (the server enforces it). */
export function adminAreas(role: Role | undefined) {
  return {
    users: role === "admin",
    groups: role === "admin",
    collections: role === "admin" || role === "editor",
    grants: role === "admin",
  };
}
