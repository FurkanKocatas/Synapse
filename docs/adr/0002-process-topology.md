# 0002. Process topology: modular monolith with separate worker processes

- Status: accepted (backups: taken from the host, [ADR 0021](0021-backups.md))
- Date: 2026-09-28

## Context

Synapse must run on one CPU-only box with 16 GB RAM, where the local LLM alone needs 3 to 6 GB. The product owner wants two properties usually associated with microservices: a failure in one part must not take down the rest, and every part must be observable (logs, traces). Large microservice deployments commonly pay for that with a shared internal secret that lets any compromised service impersonate any user, identity passed in HTTP headers between services, and diverging copies of the same auth guard.

Research: [04-architecture.md, section 1](../research/04-architecture.md).

## Decision

One Python codebase and one application image, started in different roles:

| Role | Command | Responsibility |
|---|---|---|
| `api` | `synapse api` | HTTP API, sessions, authorization, chat orchestration, streaming |
| `worker-ingest` | `synapse worker --queue ingest` | File type detection, parsing, cleaning, chunking |
| `worker-ocr` | `synapse worker --queue ocr` | OCR of scanned pages |
| `worker-embed` | `synapse worker --queue embed` | Batch embedding of chunks |
| `scheduler` | `synapse scheduler` | Periodic jobs: consistency checks, audit anchoring, backups, cleanup |

Third-party containers: PostgreSQL, one `llama-server` for chat, one `llama-server` for embeddings and reranking, Caddy (TLS termination, static frontend, reverse proxy). About 8 containers in total.

Rules that make this safe:

1. **User identity is resolved once, in `api`.** Workers never accept identity from a caller; they read job rows that record the actor and tenant.
2. **No service-to-service user calls.** Processes communicate through the database (jobs, rows) and call only the model servers.
3. **Untrusted file parsing happens only in workers**, never in `api`.
4. **Every container has a memory limit**, a healthcheck and `restart: unless-stopped`. An OOM or crash restarts one role; its jobs are retried.
5. **Every outbound call has a timeout.** Model calls pass through a semaphore sized to the model server's parallel slots, and through a circuit breaker.
6. **Degraded modes are designed, not accidental:** if the chat model is down, search still returns sources; if OCR is down, text-native documents still ingest.

Code is organized as a modular monolith with enforced boundaries (see [0015](0015-tooling-and-ci.md)); any module can later become its own process because its interface is already a Python port.

## Consequences

- Idle overhead is about 0.8 GB instead of 2 to 3 GB for 20 Python services.
- One image to build, sign, ship and upgrade; no version skew between services.
- The internal attack surface is limited to the model servers on a private network, each with its own key.
- Scaling for SaaS is per role: more `api` replicas, more workers per queue.
- A bug in shared code can affect every role at once; mitigated by tests and by the boundaries.

## Alternatives considered

- **About 20 microservices:** rejected. RAM overhead on 16 GB, N x N service authentication (the usual root of impersonation and header-trust vulnerabilities), many images and migrations to keep in step.
- **Single process:** rejected. An OCR segfault or parser OOM would kill login and chat.
