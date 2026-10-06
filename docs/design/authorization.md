# Authorization: design

Status: implemented (model and checks), 2026-09-28. Decision record: [ADR 0007](../adr/0007-authorization.md). Code: [backend/src/synapse/authz/](../../backend/src/synapse/authz/), tables and the `accessible_documents` function in migration [0005](../../backend/src/synapse/migrations/versions/0005_authorization.py).

## Two kinds of permission

| Kind | Question it answers | Where it is decided |
|---|---|---|
| Role permissions | May this role do this action? (`users.manage`, `groups.manage`, `collections.create`, `settings.manage`, `audit.read`) | The `role_permissions` table, checked by `require("...")` on the route |
| Document permissions | May this user `read`, `write` or `manage` this document? | The SQL function `accessible_documents(user, permission)` |

Role permissions per role today:

| Role | Permissions |
|---|---|
| admin | users.manage, groups.manage, collections.create, settings.manage |
| editor | collections.create |
| member | none beyond the documents granted to them |
| auditor | audit.read |

Admins manage people and permissions, but **reading a document needs a grant like anyone else**. The auditor reads the audit log, not document content.

## Document permissions

```mermaid
flowchart TD
    R["Collection: Decisions<br/>grant: group legal, read"] --> C["Collection: 2026"]
    R --> D1["Document: Rules"]
    C --> D2["Document: Decision 2026/35"]
    H["Collection: HR<br/>no grants"] --> D3["Document: Salaries<br/>grant: user Ayşe, read"]
```

- A grant names one principal (a user, a group or a role) and one level: `read`, `write` or `manage`. Higher levels include lower ones.
- A grant on a collection covers everything inside it, including nested collections. A grant on a document covers that document only.
- In the picture: members of `legal` can read both documents under Decisions; Ayşe can read Salaries; nobody else can read anything, admins included.
- Deleted documents and disabled users drop out immediately, because nothing is copied into a separate index.
- Grants cannot point into another tenant: every foreign key includes the tenant.

`accessible_documents` is the only definition of access. Search and chat will filter candidates with it inside the same SQL statement (a pre-filter), so there is no post-filter that could be skipped.

## Routes

Every route must declare how it is protected, and a test enforces it ([test_route_inventory.py](../../backend/tests/test_route_inventory.py)):

- `Depends(public_endpoint)`: deliberately reachable without a session (health checks, login).
- Any session dependency (`AnySession`, `FullSession`, `PendingSession`, `EnrollmentSession`).
- `require("permission")`: a full session whose role has the permission. A misspelled permission name fails when the route is defined.

The test also proves it can fail, with a route that forgets its guard.

## Administration API

All under `/api/admin`, each behind a role permission, each change audited in the same transaction.

| Endpoint | Permission | Notes |
|---|---|---|
| `GET /users`, `POST /users`, `PATCH /users/{id}` | `users.manage` | See [identity.md](identity.md#account-administration) |
| `GET /groups`, `POST /groups` | `groups.manage` | Names are unique per tenant (409) |
| `POST /groups/{id}/members`, `DELETE /groups/{id}/members/{user}` | `groups.manage` | Adding twice is 409, removing a non-member is 404 |
| `GET /collections`, `POST /collections` | `collections.create` | A non-admin creator gets `manage` on the new collection; an admin creator gets nothing, because admins need grants to read like anyone else |
| `GET /collections/{id}/grants`, `POST /collections/{id}/grants` | `permissions.manage` | Principal is a user or group ID, or a role name. An unknown principal or collection is 404 |
| `GET /documents/{id}/grants`, `POST /documents/{id}/grants` | `permissions.manage` | A grant on that one document, beside those on its collections; the same principals. An unknown or deleted document is 404 |
| `DELETE /grants/{id}` | `permissions.manage` | A grant on a collection or on a document |

An admin can grant themselves read access to any collection, like any other grant. The audit log records it (`authz.grant.add`, with the actor), so that is visible rather than prevented.

Audit actions: `authz.group.create`, `authz.group.member_add`, `authz.group.member_remove`, `authz.collection.create`, `authz.grant.add`, `authz.grant.remove`.

## Screens

`/admin/users`, `/admin/groups` and `/admin/collections` in the web app ([frontend/src/features/admin/](../../frontend/src/features/admin/)). The navigation shows each area only to roles that can use it, and the route guard sends anyone else home; the API still decides. Errors from the API appear as one translated sentence at the top of the page (for example "At least one active administrator must remain").

## Not in this step

- Moving or renaming collections, and a screen for document grants (the API is there).
- Retrieval using `accessible_documents` (with the knowledge base).
