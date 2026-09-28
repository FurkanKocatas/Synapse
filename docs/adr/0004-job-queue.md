# 0004. Background jobs with Procrastinate on PostgreSQL

- Status: accepted
- Date: 2026-09-28

## Context

Ingestion is low volume (hundreds to low thousands of jobs per day on-prem) and long running (seconds to minutes per document). Throughput does not matter; correctness does. "Document committed but job lost" and "job ran for a document that was rolled back" are the drift bugs [0003](0003-single-postgres-store.md) exists to prevent. Only a queue in the same database can enqueue in the same transaction as the document row.

Research: [04-architecture.md, section 2](../research/04-architecture.md).

## Decision

Use [Procrastinate](https://procrastinate.readthedocs.io/) (async, Postgres-backed, retries, periodic tasks, locks, LISTEN/NOTIFY) on the main database.

- Queues: `ingest`, `ocr`, `embed`, `maintenance`. One worker role per queue class ([0002](0002-process-topology.md)).
- Jobs are enqueued inside the transaction that creates or changes the document.
- Every job carries `tenant_id`, `actor_id` and the OpenTelemetry trace context. The task wrapper rejects a job without a tenant and sets the tenant context ([0005](0005-tenancy.md)) before touching data.
- Jobs that operate on a document take a Procrastinate lock keyed by the document id, so re-index and delete are serialized.
- Retries use exponential backoff with a cap; exhausted jobs stay visible on the admin Operations page and raise an alert.
- Bulk ingestion runs at lower concurrency during office hours, set by the scheduler, so chat keeps priority for CPU.

## Consequences

- No broker to install, secure or back up.
- Job state is inspectable with SQL.
- We depend on Procrastinate's maintenance; the task wrapper is our own thin layer, so a switch to raw `SKIP LOCKED` would stay local.

## Alternatives considered

- **Celery, Dramatiq, RQ:** need Redis or RabbitMQ and cannot enqueue transactionally with the document write.
- **arq:** maintenance only.
- **pgmq:** queue primitives only; retries, scheduling and workers would be ours to build.
- **Hand-written `FOR UPDATE SKIP LOCKED` queue:** proven pattern, but rewriting a queue library is not where our effort should go.
