# 0015. Language, repository layout, tooling and CI

- Status: accepted
- Date: 2026-09-28

## Context

Quality erodes fastest when CI exists on paper but does not run, tests sit outside every runner, linters and type checkers are effectively off, files grow without limit, customer-specific constants end up in code, and code mixes languages.

## Decision

**Language policy.** English only for code, identifiers, comments, documentation, commit messages and API error codes. Turkish appears only in UI translation files, in configuration data for Turkish text processing (stop words, lexicons, entity patterns), and in test fixtures that must be Turkish text. Customer or sector specifics live in configuration, never in code.

**Repository layout**

```
backend/            Python package `synapse` (FastAPI app, workers, CLI)
  src/synapse/
    kernel/         config, database sessions, tenancy context, logging, errors
    identity/       users, sessions, passwords, MFA
    authz/          roles, grants, retrieval filter
    audit/          hash-chained audit log
    documents/      upload, storage, versions, metadata, collections
    ingestion/      parsing, OCR, cleaning, chunking, embedding jobs
    retrieval/      candidate lists, fusion, reranking
    chat/           conversations, answer generation, verification, streaming
    admin/          settings, module registry, licence, operations page
    ports/          protocols for models, OCR, blob storage
    adapters/       implementations of the ports
    modules/        optional modules
    saas/           SaaS-only code
  tests/
frontend/           Vite + React SPA
deploy/             Compose templates, Caddy template, images
synapsectl/         installer and operations CLI
eval/               golden sets, corpora manifests, evaluation harness
docs/               adr/, research/, product/, operations/, benchmarks/
```

Each backend package exposes a `public.py`; everything else is private to the package.

**Python tooling:** Python 3.14, `uv` with a committed lockfile, `ruff` (lint with a broad rule set, and format), `mypy --strict`, `import-linter` contracts (layers, independence between sibling domains, forbidden imports such as HTTP clients outside `adapters`), `pytest` against a real PostgreSQL with pgvector (no mocked database for authorization, tenancy or retrieval tests), coverage floor raised over time.

**Frontend tooling:** `pnpm`, TypeScript strict, ESLint, Prettier, Vitest, Playwright.

**Size limits in CI:** Python files at most 800 lines, functions at most 80 lines; React component files at most 400 lines.

**CI (GitHub Actions), required on `main`:**

| Stage | Checks |
|---|---|
| Lint and format | ruff, ruff format, ESLint, Prettier |
| Types | mypy strict, tsc |
| Architecture | import-linter, size limits, i18n key parity, route authorization inventory |
| Tests | pytest on Postgres + pgvector service container, Vitest, Playwright smoke |
| RAG quality | evaluation harness on the golden set once it exists ([0010](0010-rag-pipeline.md)) |
| Supply chain | lockfile check, pip-audit, osv-scanner, gitleaks, zizmor for workflow injection, third-party actions pinned by commit SHA, read-only default permissions |
| Images | Trivy scan, SBOM with Syft, cosign signing (release workflow) |

A test asserts that every test directory is collected by a CI job, so tests cannot silently fall outside the runners.

**Commits:** Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`), in English.

## Consequences

- CI is a gate from the first commit, so debt cannot accumulate unseen.
- Strict typing and size limits slow down the first weeks slightly and pay back from then on.

## Alternatives considered

- **Poetry or pip-tools:** `uv` is faster and handles Python versions and lockfiles in one tool.
- **Python 3.13:** 3.14 is current and all heavy dependencies ship 3.14 wheels (checked 2026-09-28).
