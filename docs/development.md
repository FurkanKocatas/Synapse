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

## Database

A local PostgreSQL 18 with pgvector and pg_textsearch, built from [deploy/postgres/Dockerfile](../deploy/postgres/Dockerfile):

```bash
python3 tools/dev_secrets.py                                # once: random secrets in .dev/secrets/
docker compose -f deploy/compose.dev.yml up -d --wait db    # listens on 127.0.0.1:55432
cd backend
uv run synapse db bootstrap --admin-conninfo-file ../.dev/secrets/admin_conninfo --secrets-dir ../.dev/secrets
SYNAPSE_DB_PORT=55432 SYNAPSE_DB_USER=synapse_migrator \
  SYNAPSE_DB_PASSWORD_FILE=../.dev/secrets/db_synapse_migrator uv run synapse db migrate
```

`bootstrap` is idempotent: it creates the database, the roles and the schema if missing, and resets every role's password from its secret file. Database tests need the same running container; they create and drop their own database, and they fail (not skip) when it is not running.

## Backend

```bash
cd backend
uv sync                  # creates .venv from uv.lock
export SYNAPSE_DB_PORT=55432 SYNAPSE_DB_USER=synapse_api
export SYNAPSE_DB_PASSWORD_FILE=../.dev/secrets/db_synapse_api
export SYNAPSE_CSRF_KEY_FILE=../.dev/secrets/csrf_key SYNAPSE_TOTP_KEY_FILE=../.dev/secrets/totp_key
export SYNAPSE_LOG_FORMAT=console
uv run synapse tenant create --slug dev --name "Development"   # once; prints the tenant ID
export SYNAPSE_TENANT_ID=<the printed ID>
uv run synapse user create --email admin@example.org --name "Admin" --role admin
uv run synapse api       # API on http://127.0.0.1:8000; /healthz, /readyz, /api/docs
```

Sign-in flows and endpoints are described in [design/identity.md](design/identity.md).

A worker run on the host (`uv run synapse worker`) reads scanned pages with Tesseract, so it needs `tesseract` 5 on the PATH (Debian and Ubuntu: `apt install tesseract-ocr`); `SYNAPSE_OCR_TESSDATA_DIR` points it at the "best" models the image uses ([deploy/app/Dockerfile](../deploy/app/Dockerfile) has their URLs and checksums). To read the text with PP-OCRv6, as the image does, download the four files of this repository's release `ocr-models-1` into a directory and set `SYNAPSE_OCR_PPOCR_DIR` to it; unset, Tesseract gives the text and RapidOCR, which downloads its models the first time it runs, the second reading. Without Tesseract, scanned pages keep no text and everything else works. The backend tests replace both engines; the full-stack smoke test runs the real ones in the image.

Configuration comes from `SYNAPSE_*` environment variables ([kernel/config.py](../backend/src/synapse/kernel/config.py)). For readable logs while developing: `SYNAPSE_LOG_FORMAT=console`.

## Frontend

```bash
cd frontend
pnpm install
pnpm dev                 # http://localhost:5173, /api is proxied to http://127.0.0.1:8000
SYNAPSE_API_URL=http://127.0.0.1:8765 pnpm dev   # proxy to an API on another port
```

Components from shadcn/ui are added with its CLI, run on demand from `frontend/`: `pnpm dlx shadcn@4.21.0 add <component>` (settings in `components.json`). The CLI is not a dependency: its file matching pulls in `braces`, which has a high advisory without a fix (GHSA-vfj7-8cjw-p6xm), and `pnpm audit` gates CI. The CSS the package provides is copied into `src/styles/shadcn.css`.

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

# Installer, from synapsectl/
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest --cov

# Frontend, from frontend/
pnpm lint && pnpm typecheck && pnpm format:check && pnpm i18n:check && pnpm test && pnpm build

# Repository, from the root
python3 tools/check_file_size.py
```

CI additionally runs the licence check, dependency vulnerability audits, a secret scan over the full git history, a workflow security audit, the full-stack smoke test (`tools/stack_smoke.sh`, see [deployment.md](deployment.md)) and an image vulnerability scan.

## Rules that CI enforces

- Python files at most 800 lines; React and TypeScript files at most 400 lines.
- Module boundaries in `backend/pyproject.toml` (`[tool.importlinter]`): higher layers may import lower ones, never the reverse. Add each new package to the contract when you create it.
- Test warnings are errors.
- Every API route is explicitly public or requires a session ([design/authorization.md](design/authorization.md#routes)).
- API docs are off unless `SYNAPSE_API_DOCS=true` (useful locally at `/api/docs`).
- No `toUpperCase()` or `toLowerCase()` on user-visible text in the frontend (Turkish casing), and no `dangerouslySetInnerHTML`.
- Only licences allowed by [ADR 0016](adr/0016-dependency-licence-policy.md); reviews are recorded in [licences.md](licences.md).

## Not enforced yet

These are decided in the ADRs and will be added as the code they apply to lands:

- RAG evaluation gate ([ADR 0010](adr/0010-rag-pipeline.md)): needs the pipeline and the golden set.
- SBOMs and image signing: need a release workflow.
- A check that every test directory is collected by a CI job: needs more than one test tree.
