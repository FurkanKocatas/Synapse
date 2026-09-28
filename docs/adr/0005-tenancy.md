# 0005. Tenancy: tenant column with forced row-level security

- Status: accepted
- Date: 2026-09-28

## Context

On-prem is the primary target, but a SaaS edition must come from the same codebase and must not be a second-class fork. On-prem customers must not pay for SaaS complexity, and SaaS isolation must not depend on every developer remembering a `WHERE tenant_id = ...`.

Research: [04-architecture.md, section 3](../research/04-architecture.md).

## Decision

- Every tenant-owned table has `tenant_id uuid NOT NULL`, row-level security enabled **and forced**, and a policy `tenant_id = current_setting('app.tenant_id', true)::uuid`.
- The application sets the tenant with `set_config('app.tenant_id', ..., true)` at the start of every transaction (transaction-scoped, safe with connection pooling). A missing setting yields `NULL`, which matches no rows: fail closed.
- Runtime database roles do not own the tables and have no `BYPASSRLS`. Schema changes run under a separate migrator role.
- **On-prem is one tenant through the same code path.** The installer creates a single tenant; the tenant is resolved from configuration instead of the hostname. RLS is therefore exercised on every install, not only in SaaS.
- SaaS-only concerns (signup, billing, per-tenant quotas, subdomain routing, connection pooling) live in a `synapse.saas` package that core code may not import (enforced by import-linter).
- Blob keys are prefixed `tenants/{tenant_id}/`. In-process caches are keyed by tenant.
- BM25 corpus statistics are computed per index; SaaS tenants that must not share term statistics are separated by partition. Customers that contractually require physical separation get a dedicated instance built from the on-prem artifact.

## Consequences

- A forgotten filter in a query returns nothing instead of another tenant's data.
- Every transaction must set the tenant; this is done by one database session helper, and a test fails if a query runs without it.
- Cross-tenant operations (vendor support tooling in SaaS) need an explicit, audited path.

## Alternatives considered

- **Schema per tenant:** catalog bloat and N migration runs; poor fit for many small tenants.
- **Database per tenant:** strongest isolation, highest operating cost; offered as the dedicated-instance tier instead.
- **Application-level filtering only:** one missed filter leaks data.
