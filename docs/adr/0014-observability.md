# 0014. Observability: OpenTelemetry and structured logs, light by default

- Status: accepted
- Date: 2026-09-28

## Context

The product owner wants every failure to be traceable. A full Prometheus, Loki, Tempo and Grafana stack costs 1.5 to 3 GB of RAM, which the 16 GB tier cannot afford. Swallowed exceptions are the other common cause of invisible failures.

Research: [04-architecture.md, section 1.4](../research/04-architecture.md).

## Decision

- **Logs:** `structlog` JSON to stdout in every process, with `request_id`, `trace_id`, `tenant_id`, `user_id` (where applicable) and `job_id` on every line. Docker `json-file` driver with rotation. Log content never includes passwords, tokens, document text or prompts; a test scans log output from the test suite for known secrets.
- **Traces and metrics:** the OpenTelemetry Python SDK with FastAPI, psycopg and httpx instrumentation from the first commit. Trace context is stored in job rows, so one trace follows an upload from the API through every worker.
- **Export:** OTLP to a configurable endpoint. On-prem default: no exporter, logs only. Optional `observability` profile runs OpenObserve (single binary). SaaS points the same exporter at a managed or self-hosted backend. The code does not change.
- **Operations page** in the admin UI: health of each role and model server, queue depths, failed and dead jobs, ingestion progress, OCR quality summary, disk usage, backup status, licence status. It reads the database and health endpoints, so it works without any observability stack.
- **No silent failures:** broad exception handlers are allowed only at process boundaries (request handler, job wrapper), where they log with context and return or record a typed error. A lint rule forbids `except Exception: pass`.
- Health endpoints: `/healthz` (process alive) and `/readyz` (dependencies reachable, schema at the expected revision, required models loaded).

## Consequences

- The 16 GB tier stays within its RAM budget.
- Deep trace analysis on-prem needs the optional profile or a support bundle.

## Alternatives considered

- **Grafana LGTM stack on-prem:** too heavy for the base tier; acceptable for SaaS.
- **SigNoz:** ClickHouse based, 1.5 to 2 GB; SaaS only.
