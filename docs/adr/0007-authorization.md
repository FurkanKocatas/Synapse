# 0007. Authorization: roles and per-document grants inside PostgreSQL

- Status: accepted
- Date: 2026-09-28

## Context

Per-document permissions are a headline feature for all three target sectors. Designs that check permissions in an external service after retrieval have a dangerous failure mode: if the service is unreachable, the check can silently turn off, and any endpoint that forgets the post-check leaks content. They also need relationships dual-written to two stores.

Research: [04-architecture.md, section 4.2](../research/04-architecture.md), [03-rag.md, section 3.8](../research/03-rag.md).

## Decision

**Model**

- Platform roles per tenant: `admin`, `editor`, `member`, `auditor`. Roles map to permissions in a table, not in code.
- Groups of users.
- Collections (folders) with grants; documents inherit their collection's grants and may add their own.
- `document_grants(document_id, principal_type, principal_id, permission)` and `collection_grants(...)`, where the principal is a user, group or role and the permission is `read`, `write` or `manage`.
- Admins manage permissions but do not automatically read every document; reading requires a grant. The auditor role reads the audit log, not document content.

**Enforcement**

- The `authz` package exposes exactly two things: a `require(permission, resource)` FastAPI dependency, and an `accessible_documents(principals, permission)` SQL function.
- **Retrieval applies the permission filter inside the same SQL statement** that runs vector and BM25 search (pre-filter), for every candidate list. There is no post-filter to forget.
- Default deny. An exception inside authorization code denies the request.
- A CI test enumerates all routes and fails if any route has neither `require(...)` nor an explicit `public` marker.
- Permission changes take effect on the next query, because nothing is copied into a separate index.

## Consequences

- One source of truth, one transaction, no drift.
- We write the permission model ourselves; it is small and heavily tested.
- Cross-organization sharing graphs (a SaaS feature some day) would need a new ADR.

## Alternatives considered

- **OpenFGA / SpiceDB:** extra stateful service, dual writes, slow list filtering at retrieval time.
- **Cerbos, Casbin:** still need the data for list filtering; weak fit for filtering inside search.
- **Oso Cloud:** SaaS dependency, unusable air-gapped.
