# 0008. Tamper-evident audit log

- Status: accepted
- Date: 2026-09-28

## Context

KVKK, the public-sector information security guide and attorney confidentiality all push customers to ask who saw what and when. Hash chains are often implemented incompletely: some columns left out of the hash, a verifier that only compares stored hashes with each other instead of recomputing them, or a retention function the application itself can call to drop old records.

Research: [04-architecture.md, section 4.3](../research/04-architecture.md).

## Decision

- Audited events: logins and failures, MFA changes, session revocations, user and permission changes, document upload, view, download, delete, every chat question with the IDs of retrieved documents, exports, settings and module changes, licence changes.
- One chain per tenant. Each row stores `seq` (gapless per tenant), `prev_hash` and `hash`.
- `hash = SHA-256(canonical bytes)` over **every column except `hash`**, serialized with RFC 8785 (JSON Canonicalization Scheme), timestamps in UTC with microseconds, and a `schema_version` field.
- A single writer per chain: inserts take `pg_advisory_xact_lock` on the tenant, so concurrent inserts cannot fork the chain.
- **The verifier recomputes** each row's hash from its contents and checks it against the stored hash, the next row's `prev_hash` and `seq` continuity.
- Database grants: runtime roles have `INSERT` and `SELECT` only; `UPDATE`, `DELETE` and `TRUNCATE` are revoked, and a trigger rejects updates. Retention (deleting old partitions) runs only as a separate, audited maintenance role.
- Security events are written in the same transaction as the action; if the audit insert fails, the action fails.
- Nightly, the scheduler signs the current chain head (tenant, seq, hash, time) with the instance Ed25519 key and exports it off the box (customer admin email, syslog, or file). This anchoring is what makes a rewrite by a database superuser detectable.
- The audit log never stores document content or passwords; questions are stored, answers are stored as a hash plus the cited document IDs (configurable per tenant).

## Consequences

- Tampering is detectable, not preventable; the export of anchors is what gives it teeth, so it is on by default.
- Audit writes serialize per tenant; acceptable at on-prem volumes, and per-tenant chains keep SaaS tenants independent.

## Alternatives considered

- **immudb or another ledger database:** extra stateful service; the signed anchor achieves the needed property.
- **Plain append-only table:** no tamper evidence.
