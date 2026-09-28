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
  status=$?
  if [ "$status" -ne 0 ]; then
    printf '\n== Smoke test failed; container logs:\n'
    stack logs --no-color --tail 60 || true
  fi
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
stack run --rm --no-deps -T -v "$password_file:/run/password:ro" api \
  user create --email editor@smoke.example --name "Smoke Editor" --role editor \
  --password-file /run/password >/dev/null

step "Start the API, the worker and the web front"
stack up -d --wait api worker web

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

step "Register a passkey and sign in with it"
uv run --directory backend python ../tools/smoke_passkey.py \
  "$base" "http://localhost:$port" member@smoke.example "$password_file"

step "Upload a document, list it and download it"
editor_jar="$(mktemp)"
json() { python3 -c "import json, sys; print(json.load(sys.stdin)$1)"; }
csrf="$(curl -fsS -c "$editor_jar" -H 'X-Synapse-Client: web' -H 'Content-Type: application/json' \
  -X POST "$base/api/auth/login" \
  -d '{"email": "editor@smoke.example", "password": "a long smoke test passphrase"}' | json "['csrf_token']")"
editor() { curl -fsS -b "$editor_jar" -H "X-Synapse-CSRF: $csrf" "$@"; }
collection="$(editor -H 'Content-Type: application/json' -X POST "$base/api/admin/collections" \
  -d '{"name": "Smoke"}' | json "['id']")"
sample="$(mktemp)"
# A real PDF with a text layer, from the test helpers, so the worker has something to read.
uv run --directory backend python -c \
  "import sys; from tests.knowledge_samples import pdf; sys.stdout.buffer.write(pdf('Karar 2026/35 kabul edildi.'))" \
  > "$sample"
document="$(editor -H 'Content-Type: application/octet-stream' --data-binary "@$sample" \
  -X POST "$base/api/collections/$collection/documents?filename=Karar%202026-35.pdf" | json "['id']")"
editor "$base/api/collections/$collection/documents" | grep -q '"title":"Karar 2026-35"'
editor -o "$sample.back" "$base/api/documents/$document/versions/1/file"
cmp "$sample" "$sample.back"

step "Wait for the worker to extract the text"
parsed=""
for _ in $(seq 60); do
  status="$(editor "$base/api/documents/$document/versions" | json "[0]['status']")"
  if [ "$status" = "parsed" ]; then parsed=yes; break; fi
  if [ "$status" = "failed" ]; then break; fi
  sleep 1
done
if [ -z "$parsed" ]; then
  echo "version status: $status, failure: $(editor "$base/api/documents/$document/versions" | json "[0]['failure']")"
  exit 1
fi
stack exec -T db psql -U postgres -d synapse -Atc \
  "SELECT text FROM synapse.document_pages p JOIN synapse.document_versions v ON v.id = p.version_id
   WHERE v.document_id = '$document'" | grep -q "Karar 2026/35 kabul edildi."
rm -f "$editor_jar" "$sample" "$sample.back"

step "Check the audit log recorded the sign-in and is intact"
report="$(stack exec -T api synapse audit verify | tail -n 1)"
grep -q '"ok": true' <<<"$report"

step "Smoke test passed"
