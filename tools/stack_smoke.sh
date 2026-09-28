#!/usr/bin/env bash
# End-to-end check of the full stack built from this repository: fresh database, bootstrap,
# migrations, a tenant and an account created with the CLI, then a sign-in through the web
# front. Runs in its own compose project and removes everything it created when it exits.
#
# Usage: tools/stack_smoke.sh      (needs Docker; used by CI)

set -euo pipefail
cd "$(dirname "$0")/.."

project="synapse-smoke-$$"
port="${SYNAPSE_SMOKE_PORT:-8481}"
env_name="smoke-$$.env"
password_file="$(mktemp)"
jar="$(mktemp)"
export SYNAPSE_STACK_PORT="$port" SYNAPSE_STACK_ENV="$env_name"
# A subnet of its own, so it can run next to a development stack.
export SYNAPSE_STACK_SUBNET="${SYNAPSE_SMOKE_SUBNET:-172.29.201.0/24}"

stack() { docker compose -p "$project" -f deploy/compose.stack.yml "$@"; }
cleanup() {
  stack down -v --remove-orphans >/dev/null 2>&1 || true
  rm -f ".dev/$env_name" "$password_file" "$jar"
}
trap cleanup EXIT

step() { printf '\n== %s\n' "$*"; }

python3 tools/dev_secrets.py

step "Build images and start the database, bootstrap and migrations"
stack build --quiet
stack up -d --wait db
stack run --rm bootstrap
stack run --rm migrate

step "Create a tenant and an account with the CLI"
tenant_id="$(stack run --rm --no-deps -T api tenant create --slug smoke --name "Smoke" | tail -n 1)"
echo "SYNAPSE_TENANT_ID=$tenant_id" > ".dev/$env_name"
printf 'a long smoke test passphrase' > "$password_file"
chmod 644 "$password_file"
stack run --rm --no-deps -T -v "$password_file:/run/password:ro" api \
  user create --email member@smoke.example --name "Smoke Member" --role member \
  --password-file /run/password >/dev/null

step "Start the API and the web front"
stack up -d --wait api web

base="http://127.0.0.1:$port"
step "Check the web front and the API through it"
curl -fsS -o /dev/null "$base/"
curl -fsS -o /dev/null "$base/login"
headers="$(curl -fsSI "$base/")"
grep -qi "content-security-policy: default-src 'self'" <<<"$headers"
grep -qi "x-content-type-options: nosniff" <<<"$headers"

login="$(curl -fsS -c "$jar" -H 'X-Synapse-Client: web' -H 'Content-Type: application/json' \
  -X POST "$base/api/auth/login" \
  -d '{"email": "member@smoke.example", "password": "a long smoke test passphrase"}')"
grep -q '"auth_level":"full"' <<<"$login"
session="$(curl -fsS -b "$jar" "$base/api/auth/session")"
grep -q '"email":"member@smoke.example"' <<<"$session"

step "Check the audit log recorded the sign-in and is intact"
report="$(stack exec -T api synapse audit verify | tail -n 1)"
grep -q '"ok": true' <<<"$report"

step "Smoke test passed"
