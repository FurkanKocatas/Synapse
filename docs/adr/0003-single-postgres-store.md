# 0003. PostgreSQL is the only stateful store

- Status: accepted
- Date: 2026-09-28

## Context

A common design keeps vectors in a separate vector database, jobs in a message broker, caches and sessions in Redis, and documents in Postgres. Its typical failure is drift: documents marked ready without vectors, deletes racing with in-flight indexing, and re-indexing leaving stale vectors. Every extra store also meant another password, backup target and failure mode on the customer's box.

At Synapse's scale (up to about 100k chunks per install), an in-memory HNSW index of 1024-dimension half-precision vectors is about 200 MB, and query latency is single-digit milliseconds; the reranker and LLM dominate latency, not the store.

Research: [03-rag.md, section 4](../research/03-rag.md), [04-architecture.md, section 2](../research/04-architecture.md).

## Decision

A single PostgreSQL 18 instance holds:

- Documents, versions, metadata, folders, permissions, users, sessions.
- Chunks with their embeddings (`pgvector` 0.8, `halfvec`, HNSW, iterative index scans) and optional sparse vectors (`sparsevec`).
- Full-text BM25 indexes (`pg_textsearch`) over a lemma column and a raw-token column.
- Extracted entities, typed tables from spreadsheets and documents.
- The job queue ([0004](0004-job-queue.md)) and the audit log ([0008](0008-audit-log.md)).

Consistency rules:

1. A new document version's chunks, embeddings and entities, the version flip, the deletion of the previous version's chunks and `status = 'ready'` are written **in one transaction**.
2. Retrieval joins chunks on the document's current version and excludes deleted documents, so readers never see mixed versions or deleted content.
3. The ingestion worker locks the document row and re-checks `deleted_at` and `version` before committing; a delete during indexing wins.
4. A scheduled invariant check (ready documents without chunks, chunks without embeddings, orphans) must always return zero and alerts otherwise.

Blobs (original files, rendered pages) are stored on a local volume behind a `BlobStore` port, with an S3-compatible adapter for SaaS.

Caching is in-process with short TTLs. There is no Redis in v1.

## Consequences

- The index-drift class of bugs cannot happen by construction.
- One backup (`pg_dump` plus the blob directory) captures the whole state.
- Postgres memory settings must be tuned per hardware tier; the installer renders them.
- If a SaaS deployment ever needs tens of millions of vectors, a dedicated vector store can be added behind the retrieval port; that would need a new ADR and an outbox with reconciliation.

## Alternatives considered

- **Qdrant (or another vector database) plus Postgres:** rejected for v1; reintroduces dual writes and drift.
- **ParadeDB `pg_search` for BM25:** richer (phrases, fuzzy), but AGPL-3.0. Kept as a fallback if phrase queries prove necessary.
- **Native `ts_rank`:** not real BM25 (no IDF or length normalization); fallback only.
- **Redis for sessions and rate limits:** not needed on a single box; can be added behind a `CachePort` for SaaS if profiling shows a need.
