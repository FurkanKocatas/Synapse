# 00. Research Summary and Proposed Direction

Status: end of phase 1 (research), 2026-09-28. This document condenses the four research reports into the decisions they support, reconciles the points where they disagree, and lists what still has to be measured. Details and sources live in the individual reports:

- [01-market.md](01-market.md): Turkish market, competitors, regulation, pricing
- [02-hardware-inference.md](02-hardware-inference.md): CPU/GPU inference, models, OCR, hardware tiers, WSL2
- [03-rag.md](03-rag.md): parsing, chunking, retrieval, generation, evaluation
- [04-architecture.md](04-architecture.md): topology, queue, tenancy, auth, frontend, installer, security

Numbers marked as estimates in the reports are still estimates here. Nothing below has been benchmarked on a Ryzen 5 3600 yet.

---

## 1. The market position in one paragraph

Turkish enterprise AI adoption is 7.5% against 20% in the EU, and the three barriers buyers name are lack of expertise, cost and legal uncertainty. Global assistants (Copilot, ChatGPT Business, Gemini) send data abroad, which under the 2024 KVKK amendment requires a standard contract for every transfer, and which the public-sector information security guide rules out for critical data. Open-source tools are toolkits without Turkish support, document-level permissions or audit logs, and two of them (Open WebUI, Dify) have licence clauses that block white-label or multi-tenant resale. Turkish vendors are either enterprise/defence (HAVELSAN, SESTEK, CBOT) or cloud legal research. **Nobody sells a fixed-price, Turkish-first, on-premise document assistant with per-document permissions and an audit log, sized for a district municipality, a 10-lawyer firm or a private clinic.** That is the gap Synapse targets.

Pricing anchor: the 2026 direct procurement limits (1,021,827 TRY for districts inside metropolitan areas, 340,391 TRY elsewhere) define the municipal packages. Private buyers compare against roughly 11,000 TRY per user per year for Copilot or ChatGPT.

## 2. The hardware reality (the most important finding)

On a CPU-only Ryzen 5 3600, **prompt processing is the bottleneck, not generation**. Estimated full-answer time for a 3,000-token context and a 300-token answer:

| Setup | Time to first token | Full answer |
|---|---|---|
| 4B model, 16 GB RAM | 35-50 s | 55-80 s |
| 35B MoE (about 3B active), 32 GB RAM | 40-70 s | 60-90 s, far better quality |
| Any of the above + a cheap 6-8 GB GPU | about 12 s | about 30-35 s |
| 16 GB GPU (RTX 5060 Ti class) | 1-2 s | 5-8 s |

Consequences for the product:

1. **Retrieval-first UX.** Sources with highlighted passages must appear within a few seconds, before and independent of the LLM answer. Search alone is useful on CPU.
2. **Context budget is a latency budget.** Retrieval precision directly buys speed: final context capped at 6 chunks and about 1,500-3,000 tokens.
3. **The CPU tier is the entry tier, not the recommended one.** 16 GB CPU works for 5-10 named users with 1-2 simultaneous answers. Upgrading to 32 GB (unlocks MoE models) or adding even a used 8 GB GPU is the best value step, and the sales packages should say so.
4. **First-time ingestion of 10,000 documents on CPU is a multi-day, resumable, night-time batch job** (parse, OCR, embed). On a 16 GB GPU it is a few hours.

## 3. Proposed architecture (needs your approval)

**Modular monolith with separate worker processes**, not about 20 microservices.

- One application image started in several roles: `api`, `worker-ingest`, `worker-ocr`, `worker-embed`, `scheduler`.
- Separate containers for Postgres, the chat model server, the embedding/rerank model server and Caddy (TLS, static frontend).
- About 8 containers in total.

Why this instead of microservices, given your goals:

| Your goal | How it is met |
|---|---|
| One failure must not take down the system | Each role is its own OS process and container with its own memory limit. An OCR crash or OOM restarts only the OCR worker; login and chat keep working. Untrusted file parsing only happens in workers. Timeouts, circuit breakers and degraded modes (search works when the LLM is down) on every boundary. |
| Logging and tracing | OpenTelemetry in every process from day one, trace context carried through job payloads, structured JSON logs with request, job and tenant IDs. An optional lightweight observability profile (OpenObserve, single binary) on-prem. |
| Modularity | Hexagonal package layout with enforced boundaries (import-linter contracts in CI), 800-line file limit. Any module can be extracted into its own service later, because its interface is already a Python port. |

What it avoids: 20 Python services would cost 2-3 GB of idle RAM on a 16 GB box, and service-to-service calls would bring back the shared-secret and header-identity trust mesh behind the most common impersonation vulnerabilities.

Other core decisions from [04-architecture.md](04-architecture.md):

| Area | Decision |
|---|---|
| Data store | One Postgres (17/18) holds documents, permissions, chunks, vectors (pgvector), BM25 (pg_textsearch), jobs, sessions and audit. Chunks, vectors and "ready" status are written in one transaction, so the index cannot drift from the database. No Qdrant, no Redis in v1 |
| Queue | Procrastinate on the same Postgres: a job is enqueued in the same transaction as the document row, with per-document locks so delete and re-index cannot race |
| Tenancy | `tenant_id` + forced row-level security everywhere. On-prem is simply one tenant through the same code path. SaaS-only code (signup, billing, quotas) in an isolated `saas` package |
| Authentication | Own small identity package: Argon2id, NIST SP 800-63B-4 password rules, server-side session cookies (no JWT), TOTP + passkeys, MFA mandatory for admins, backoff throttling. OIDC later |
| Authorization | Roles + per-document grants in Postgres; the permission filter is inside the retrieval SQL itself. Default deny; a CI test fails if any route lacks an explicit permission check |
| Audit | Hash chain over every column (canonical JSON), single writer, a verifier that recomputes hashes, insert-only DB grants, nightly signed checkpoints exported off the box |
| Model runtime | llama.cpp `llama-server` for chat, embeddings and rerank (one format, one API, CPU and every GPU vendor). vLLM only as an opt-in engine for large GPU installs. External APIs opt-in, logged, with PII masking first |
| Frontend | Vite + React + TypeScript static SPA served by Caddy (no Node server), shadcn/ui, TanStack Router/Query, Paraglide for TR/EN with compile-time missing-key errors |
| Installer | Vendor-operated `synapsectl` with one `synapse.toml` source of truth and an interactive wizard; `init`, `apply`, `doctor`, `backup`, `restore`, `upgrade`. Modules have manifests and are active only when enabled, licensed and migrated. Disabling never drops data |
| Licensing | Offline Ed25519-signed licence bound to the install. Expiry never locks customers out of their own data |
| Secrets | Generated at install, one credential per process, mounted as files, never in env vars or git |
| CI | GitHub Actions from the first commit: ruff, mypy strict, tsc, import-linter, pytest on a real Postgres, vitest, Playwright, dependency and secret scanning, image signing |

## 4. Proposed RAG pipeline v1

From [03-rag.md](03-rag.md), adjusted by the hardware findings:

1. **Parse:** Docling (MIT) with a router by file type. Every page gets an OCR quality check (Turkish character profile, dotted/dotless i ratio, lexicon hit rate, markup artifacts); failing pages are re-OCR'd, low-quality pages are flagged in the admin UI.
2. **Clean and extract:** drop repeated headers/footers, strip hidden text, attach signature blocks as metadata, Turkish-aware Unicode and casing. Extract typed entities (decision numbers, regulation numbers, dates, amounts, parcels) into their own table.
3. **Chunk:** structure-aware, about 350 tokens, never crossing major headings, **never splitting a table row**. Large tables split by row groups with repeated headers, plus a table summary chunk, plus a copy in a typed SQL table for calculations.
4. **Deduplicate:** file hash, MinHash at document level, SimHash at chunk level; duplicates become links, not new vectors.
5. **Contextual prefix:** deterministic (title, type, date, number, heading path, page) always; an LLM-written document summary in the background once per document.
6. **Retrieve:** four candidate lists merged with weighted RRF, all with the permission filter in SQL: exact identifier match, BM25 on Turkish lemmas, BM25 on raw words, dense vectors. **Fusion scores are never thresholded.**
7. **Rerank:** cross-encoder over the top candidates; thresholds only on its calibrated scores.
8. **Refuse early:** if the best reranker score is below a threshold set from the golden set, answer "not found in the documents" and list possibly related documents, without calling the LLM.
9. **Generate:** small model, structured JSON output with `answer`, `citations` and `sufficient`. Aggregation questions go to a read-only SQL/calculator tool; the model never adds numbers itself.
10. **Verify:** every number and identifier in the answer must appear in the cited sources or in tool output. Citations resolve to document + page + highlighted region.
11. **Evaluate:** per-customer golden set (150-300 questions, 15% unanswerable). CI blocks any change that lowers retrieval metrics or produces an unsupported number.

v1 targets: Hit@10 at least 95%, Hit@1 at least 75%, identifier Hit@1 at least 98%, refusal on unanswerable at least 90%, unsupported numbers 0.

## 5. Where the reports disagree, and the resolution

| Topic | Disagreement | Resolution |
|---|---|---|
| Embedding model | 03 picks BGE-M3 (dense + sparse in one pass). 02 notes BGE-M3 needs 8-16 h to index 50k chunks on CPU against 3-6 h for multilingual-e5-base, and that e5-large leads TR-MTEB | Embedder is a per-tier setting behind one interface. Candidates: BGE-M3, multilingual-e5-base/large, EmbeddingGemma-300M, turkish-e5-large. Decide by bake-off on our Turkish golden set, measuring recall and chunks/s on the target CPU |
| Reranker cost on CPU | 03 estimates 1.5-3 s for 30 pairs; 02 estimates 10-30 s | Unknown until measured. Candidate count and passage length are tier settings (CPU: top 10-15 at 256 tokens; GPU: top 30-50). Also measure "no reranker" |
| OCR engine | 03 recommends PP-OCRv5 Latin. 02 found the PaddleOCR maintainers saying Turkish special characters were not covered in that model | Tesseract `tur` (Apache 2.0) is the safe default. PP-OCRv5 only after we verify its current dictionary handles ç ğ ı İ ö ş ü. The per-page quality check applies to all engines |
| Default chat model | 04's RAM budget assumes an 8B model; 02 and 03 say 4B on 16 GB, 35B MoE on 32 GB | 16 GB: 4B class (Qwen3.5-4B or Gemma 4 E4B). 32 GB: 30-35B MoE. GPU: by VRAM. Final pick by our Turkish grounded-QA benchmark |
| GPU prices | RTX 5060 Ti 16 GB: 26-40k TRY (akakce) vs 50-58k TRY (cimri) | Prices are volatile because of the DRAM shortage; re-quote at sale time, never hold stock |
| BM25 engine | ParadeDB is richer but AGPL | pg_textsearch (PostgreSQL licence) by default |

## 6. Licence exclusions

Not shippable in a closed commercial product without a separate licence: jina embeddings and rerankers (CC BY-NC), Marker and Surya (GPL + revenue cap on weights), MinerU and PyMuPDF (AGPL), ParadeDB community (AGPL), Open WebUI (branding clause), Dify (multi-tenant clause). Model licences (Qwen: Apache 2.0; Gemma: Gemma terms) must be checked for redistribution inside an appliance.

## 7. Scope for v1

In: knowledge base (upload, folders, versions, permissions), ingestion for PDF (born-digital and scanned), DOCX, XLSX, PPTX; hybrid retrieval and grounded chat with page-level citations; users, groups, roles, per-document permissions, audit log; local login with MFA; TR/EN UI; installer wizard with module registry; offline licence; backup and restore; evaluation harness.

Planned as optional modules, not built in v1: report generation, specification drafting, translation, calendar. Discussed separately: the website chatbot (widget), possibly as its own product.

Out of v1 (per the market report): clinical decision support, public case law search. Positioning: the customer's own archive and procedures, with cited answers.

## 8. What must be measured before promising anything

1. `llama-bench` on a real Ryzen 5 3600 (16 and 32 GB) for the candidate models, including the risk that Qwen3.5's new attention architecture runs slowly on CPU.
2. End-to-end RAG latency at 1,500 and 3,000 context tokens with 1, 2 and 4 parallel users.
3. Embedding bake-off (recall and chunks/s) and reranker gain vs latency.
4. OCR character accuracy on Turkish scans.
5. The same tests on a WSL2 host with 16 and 32 GB.
6. A Turkish grounded-QA set across municipal, legal and health documents, with answerable and unanswerable questions.

## 9. Open points

- **Name.** "Synapse" is high risk (Azure Synapse, Matrix Synapse, and Fujifilm Synapse, a healthcare IT product sold in Turkey). Keep it as a code name; pick a distinctive product name and check TÜRKPATENT classes 9 and 42 before public use.
- **Benchmark hardware.** A real Ryzen 5 3600-class machine is needed for section 8.
- **Evaluation corpus.** A Turkish golden set needs real documents we are allowed to use (public municipal decisions and regulations are candidates).
