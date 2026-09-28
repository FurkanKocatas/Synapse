#!/usr/bin/env bash
# Every check CI runs that does not need network access to package registries, in one command.
# Run it before each commit; it stops at the first failure.
#
# Usage: tools/check_all.sh [--with-stack]   (--with-stack also runs the full-stack smoke test)

set -euo pipefail
cd "$(dirname "$0")/.."

step() { printf '\n== %s\n' "$*"; }

step "Backend"
(
  cd backend
  uv run ruff check . ../tools ../eval
  uv run ruff format --check . ../tools ../eval
  uv run mypy src tests ../tools/check_file_size.py ../tools/check_licences.py ../eval/corpus/fetch.py
  uv run lint-imports
  uv run pytest --cov -q
)

step "Installer"
(
  cd synapsectl
  uv run ruff check .
  uv run ruff format --check .
  uv run mypy src tests
  uv run pytest --cov -q
)

step "Frontend"
(
  cd frontend
  pnpm lint
  pnpm typecheck
  pnpm format:check
  pnpm i18n:check
  pnpm test
  pnpm build >/dev/null
)

# Fails if git grep finds anything. git grep exits 0 on a match, 1 on none and higher on an
# error; an error must fail the check too, or a broken pattern would pass silently.
forbid() {
  local description="$1"
  shift
  local status=0
  git grep "$@" || status=$?
  case "$status" in
    0) echo "$description found" >&2; exit 1 ;;
    1) ;;
    *) echo "could not check for $description (git grep exit $status)" >&2; exit 1 ;;
  esac
}

step "Repository rules"
python3 tools/check_file_size.py
# House style: no em or en dashes in any text. The pattern is built from their UTF-8 bytes, so
# this file does not contain the characters it forbids.
dashes="$(printf '\xe2\x80\x93|\xe2\x80\x94')"
forbid "an em or en dash" -nE "$dashes" -- . ':!*.lock' ':!frontend/pnpm-lock.yaml'

if [[ "${1:-}" == "--with-stack" ]]; then
  step "Full stack"
  tools/stack_smoke.sh
fi

step "All checks passed"
