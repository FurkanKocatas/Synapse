# Documentation

| Folder | Contents |
|---|---|
| [product/](product/) | What we are building and for whom: [vision.md](product/vision.md), [v1-scope.md](product/v1-scope.md), [modules.md](product/modules.md) |
| [adr/](adr/) | Architecture decision records: one decision per file, with context and rejected alternatives |
| [deployment.md](deployment.md) | Images, container hardening, the full stack and its smoke test |
| [installer.md](installer.md) | synapsectl: synapse.toml, secrets, rendering, doctor, backups and restores |
| [plan/](plan/) | Work plans per phase: [phase-4.md](plan/phase-4.md) (knowledge base and RAG) |
| [design/](design/) | How implemented parts work: [identity.md](design/identity.md), [audit.md](design/audit.md), [authorization.md](design/authorization.md), [knowledge-base.md](design/knowledge-base.md), [search.md](design/search.md), [answers.md](design/answers.md), [evaluation.md](design/evaluation.md), [backup.md](design/backup.md) |
| [benchmarks/](benchmarks/) | Measurements behind defaults: [page-quality.md](benchmarks/page-quality.md), [ocr.md](benchmarks/ocr.md), [parsing.md](benchmarks/parsing.md), [embeddings.md](benchmarks/embeddings.md) (retrieval, encoders, reranking), [answers.md](benchmarks/answers.md) (chat models, and answers in the product), [refusal.md](benchmarks/refusal.md) (refusal before generation) |
| [research/](research/) | The evidence behind the decisions: market, hardware, RAG, architecture. Start with [00-summary.md](research/00-summary.md) |

## Architecture decisions

| ADR | Decision |
|---|---|
| [0001](adr/0001-record-architecture-decisions.md) | Record architecture decisions |
| [0002](adr/0002-process-topology.md) | Modular monolith with separate worker processes |
| [0003](adr/0003-single-postgres-store.md) | PostgreSQL is the only stateful store |
| [0004](adr/0004-job-queue.md) | Background jobs with Procrastinate on PostgreSQL |
| [0005](adr/0005-tenancy.md) | Tenant column with forced row-level security |
| [0006](adr/0006-authentication.md) | Local accounts with server-side sessions |
| [0007](adr/0007-authorization.md) | Roles and per-document grants inside PostgreSQL |
| [0008](adr/0008-audit-log.md) | Tamper-evident audit log |
| [0009](adr/0009-model-runtime.md) | llama.cpp behind provider ports |
| [0010](adr/0010-rag-pipeline.md) | RAG pipeline v1 and its quality gates |
| [0011](adr/0011-frontend.md) | Static React SPA with compile-time checked translations |
| [0012](adr/0012-installer-modules-licensing.md) | Installer, module registry and offline licensing |
| [0013](adr/0013-secrets-and-network-security.md) | Secrets, credentials and network security |
| [0014](adr/0014-observability.md) | OpenTelemetry and structured logs, light by default |
| [0015](adr/0015-tooling-and-ci.md) | Language, repository layout, tooling and CI |
| [0016](adr/0016-dependency-licence-policy.md) | Dependency and model licence policy |
| [0017](adr/0017-data-access.md) | psycopg 3 with explicit SQL, migrations with Alembic |
| [0018](adr/0018-model-defaults.md) | Model defaults: bge-m3, bge-reranker-v2-m3 and Qwen3.5-4B on llama.cpp |
| [0019](adr/0019-page-ocr.md) | Page OCR: PP-OCRv6 with a Turkish language model |
| [0020](adr/0020-ocr-vote.md) | Page OCR: a vote of three readings |
| [0021](adr/0021-backups.md) | Backups are taken from the host, into a restic repository |
