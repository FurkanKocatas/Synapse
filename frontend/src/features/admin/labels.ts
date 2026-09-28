// Translated names for the fixed values the API uses.

import { m } from "@/paraglide/messages.js";

import type { Permission, PrincipalType, Role } from "./adminApi";

export const roleLabel: Record<Role, () => string> = {
  admin: m.role_admin,
  editor: m.role_editor,
  member: m.role_member,
  auditor: m.role_auditor,
};

export const permissionLabel: Record<Permission, () => string> = {
  read: m.permission_read,
  write: m.permission_write,
  manage: m.permission_manage,
};

export const principalLabel: Record<PrincipalType, () => string> = {
  user: m.principal_user,
  group: m.principal_group,
  role: m.principal_role,
};
