# Development

How to set up a machine, run the parts, and run the same checks CI runs.

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.14 | Installed and managed by `uv`; no system Python needed |
| uv | 0.11 or later | Package and environment manager for the backend |
| Node.js | 24 LTS or later | Frontend build only; production serves static files |
| pnpm | Version pinned in `frontend/package.json` (`packageManager`) | Enable with `corepack enable` |
| Git | Any recent version | See identity below |

Git identity for this repository (set per clone, not globally):

```bash
git config user.name "Furkan Kocataş"
git config user.email atheron112@gmail.com
```

## Backend

```bash
cd backend
uv sync                  # creates .venv from uv.lock
uv run synapse api       # API on http://127.0.0.1:8000, health at /healthz
```

Configuration comes from `SYNAPSE_*` environment variables ([kernel/config.py](../backend/src/synapse/kernel/config.py)). For readable logs while developing: `SYNAPSE_LOG_FORMAT=console`.

## Frontend

```bash
cd frontend
pnpm install
pnpm dev                 # http://localhost:5173, /api is proxied to the backend
```

Translations live in `frontend/messages/tr.json` and `frontend/messages/en.json`. Paraglide compiles them into typed functions under `src/paraglide/` (generated, not committed). Add every new key to both files; the build fails on a key missing from Turkish, and `pnpm i18n:check` fails on any difference between the two.

## Checks

The same commands CI runs ([.github/workflows/ci.yml](../.github/workflows/ci.yml)):

```bash
# Backend, from backend/
uv run ruff check . ../tools ../eval
uv run ruff format --check . ../tools ../eval
uv run mypy src tests ../tools/check_file_size.py ../tools/check_licences.py ../eval/corpus/fetch.py
uv run lint-imports
uv run pytest --cov

# Frontend, from frontend/
pnpm lint && pnpm typecheck && pnpm format:check && pnpm i18n:check && pnpm test && pnpm build

# Repository, from the root
python3 tools/check_file_size.py
```

CI additionally runs the licence check, dependency vulnerability audits, a secret scan over the full git history and a workflow security audit.

## Rules that CI enforces

- Python files at most 800 lines; React and TypeScript files at most 400 lines.
- Module boundaries in `backend/pyproject.toml` (`[tool.importlinter]`): higher layers may import lower ones, never the reverse. Add each new package to the contract when you create it.
- Test warnings are errors.
- No `toUpperCase()` or `toLowerCase()` on user-visible text in the frontend (Turkish casing), and no `dangerouslySetInnerHTML`.
- Only licences allowed by [ADR 0016](adr/0016-dependency-licence-policy.md); reviews are recorded in [licences.md](licences.md).

## Not enforced yet

These are decided in the ADRs and will be added as the code they apply to lands:

- Route authorization inventory test ([ADR 0007](adr/0007-authorization.md)): needs the first authenticated routes.
- Tests against a real PostgreSQL service in CI ([ADR 0015](adr/0015-tooling-and-ci.md)): needs the database layer.
- RAG evaluation gate ([ADR 0010](adr/0010-rag-pipeline.md)): needs the pipeline and the golden set.
- Container image scanning, SBOM and signing: needs the first images.
- A check that every test directory is collected by a CI job: needs more than one test tree.
