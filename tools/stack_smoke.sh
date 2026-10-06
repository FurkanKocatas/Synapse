#!/usr/bin/env bash
# End-to-end check of the full stack built from this repository: fresh database, bootstrap,
# migrations, a tenant and an account created with the CLI, then a sign-in through the web
# front. Runs in its own compose project and removes everything it created when it exits.
#
# Usage: tools/stack_smoke.sh [--with-backup]      (needs Docker; used by CI)
#        tools/stack_smoke.sh --with-models [--vulkan]
#
# --with-models also starts the model servers (ADR 0018) from the files in SYNAPSE_MODELS_DIR
# (default .dev/models; synapsectl models fetch): documents must reach "ready" with their
# vectors, and the API's own adapters must get answers from the reranker and the chat model.
# --vulkan runs them on the GPU (deploy/compose.vulkan.yml). CI has no model files.
# --with-backup (needs sudo without a password; CI) then backs the installation up with
# synapsectl's code, removes it with its volumes, restores it from the backup and checks the
# documents, their files and the audit log came back, and that it takes new uploads.

set -euo pipefail
cd "$(dirname "$0")/.."

with_models="" vulkan="" with_backup=""
for argument in "$@"; do
  case "$argument" in
    --with-models) with_models=1 ;;
    --with-backup) with_backup=1 ;;
    --vulkan) vulkan=1 ;;
    *) echo "unknown argument: $argument" >&2; exit 2 ;;
  esac
done
files=(-f deploy/compose.stack.yml)
model_servers=()
if [ -n "$with_models" ]; then
  models_dir="$(realpath "${SYNAPSE_MODELS_DIR:-.dev/models}")"
  accelerator=cpu
  if [ -n "$vulkan" ]; then
    accelerator=vulkan
    files+=(-f deploy/compose.vulkan.yml)
    SYNAPSE_RENDER_GID="$(stat -c %g /dev/dri/renderD128)"
    SYNAPSE_VIDEO_GID="$(stat -c %g /dev/dri/card0)"
    export SYNAPSE_RENDER_GID SYNAPSE_VIDEO_GID
  fi
  uv run --directory synapsectl synapsectl --config /nonexistent models check \
    --dir "$models_dir" --accelerator "$accelerator"
  export SYNAPSE_STACK_MODELS=1 SYNAPSE_MODELS_DIR="$models_dir"
  files+=(--profile models)
  model_servers=(llm-embed llm-rerank llm-chat)
fi
if [ -n "$with_backup" ]; then
  # synapsectl runs as root on a customer's machine, and so does its backup here.
  sudo -n true || { echo "--with-backup needs sudo without a password" >&2; exit 2; }
  uv sync --locked --quiet --directory synapsectl
fi

project="synapse-smoke-$$"
port="${SYNAPSE_SMOKE_PORT:-8481}"
env_name="smoke-$$.env"
password_file="$(mktemp)"
jar="$(mktemp)"
export SYNAPSE_STACK_PORT="$port" SYNAPSE_STACK_ENV="$env_name"
# A subnet of its own, so it can run next to a development stack.
export SYNAPSE_STACK_SUBNET="${SYNAPSE_SMOKE_SUBNET:-172.29.201.0/24}"

stack() { docker compose -p "$project" "${files[@]}" "$@"; }
cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    printf '\n== Smoke test failed; container logs:\n'
    stack logs --no-color --tail 60 || true
  fi
  stack down -v --remove-orphans >/dev/null 2>&1 || true
  rm -f ".dev/$env_name" "$password_file" "$jar"
  # the backup's repository and staging directory belong to root
  if [ -n "${backup_work:-}" ]; then sudo rm -rf "$backup_work"; fi
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

step "Start the API, the worker, the scheduler and the web front${with_models:+, and the model servers}"
stack up -d --wait api worker scheduler web "${model_servers[@]}"

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
# Signs the editor in; prints the session's CSRF token.
sign_in_editor() {
  curl -fsS -c "$editor_jar" -H 'X-Synapse-Client: web' -H 'Content-Type: application/json' \
    -X POST "$base/api/auth/login" \
    -d '{"email": "editor@smoke.example", "password": "a long smoke test passphrase"}' | json "['csrf_token']"
}
csrf="$(sign_in_editor)"
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
# The web front logs every request with its headers; the CSRF token must not be among them.
web_log="$(stack logs --no-color web)"
grep -q '"uri":"/api/collections/' <<<"$web_log"  # the editor's requests are there
if grep -qF "$csrf" <<<"$web_log"; then echo "the access log holds the CSRF token" >&2; exit 1; fi
if grep -qF "Karar%202026-35" <<<"$web_log"; then echo "the access log holds a file name" >&2; exit 1; fi
# A request body past 1 MB that is not an upload never reaches the API.
too_big="$(head -c 2000000 /dev/zero | curl -s -o /dev/null -w '%{http_code}' -b "$editor_jar" \
  -H "X-Synapse-CSRF: $csrf" -H 'Content-Type: application/json' --data-binary @- \
  -X POST "$base/api/search")"
if [[ "$too_big" != 413 ]]; then echo "a 2 MB search got $too_big, not 413" >&2; exit 1; fi

# Waits until a document's first version is done (parsed, or ready with the model servers);
# fails on failed or after $2 seconds.
done_status="${with_models:+ready}"
done_status="${done_status:-parsed}"
wait_parsed() {
  local status=""
  for _ in $(seq "$2"); do
    status="$(editor "$base/api/documents/$1/versions" | json "[0]['status']")"
    if [ "$status" = "$done_status" ]; then return 0; fi
    if [ "$status" = "failed" ]; then break; fi
    sleep 1
  done
  echo "version status: $status, failure: $(editor "$base/api/documents/$1/versions" | json "[0]['failure']")"
  return 1
}
page_query() {
  stack exec -T db psql -U postgres -d synapse -Atc \
    "SELECT $2 FROM synapse.document_pages p JOIN synapse.document_versions v ON v.id = p.version_id
     WHERE v.document_id = '$1' ORDER BY p.number"
}

step "Wait for the worker to extract the text"
wait_parsed "$document" 60
page_query "$document" text | grep -q "Karar 2026/35 kabul edildi."

step "Upload a scanned PDF and wait for OCR"
# An image-only page, as a scanner makes: the worker must read it with both OCR engines, in
# a read-only container without network.
uv run --directory backend python -c \
  "import sys; from tests.knowledge_samples import scanned_pdf; sys.stdout.buffer.write(scanned_pdf('Karar 2026/35 kabul edildi.', 'Tutar 12.500 TL, tarih 15.03.2026.'))" \
  > "$sample"
scanned="$(editor -H 'Content-Type: application/octet-stream' --data-binary "@$sample" \
  -X POST "$base/api/collections/$collection/documents?filename=Tarama.pdf" | json "['id']")"
wait_parsed "$scanned" 240
read_back="$(page_query "$scanned" "text_source || ' ' || ocr_engine || ' ' || text")"
echo "$read_back"
grep -q "^ocr vote-ppocrv6-tr-lm+ppocrv5-latin-lm+tesseract-tur+eng " <<<"$read_back"
grep -q "Karar 2026/35 kabul edildi" <<<"$read_back"
grep -q "15.03.2026" <<<"$read_back"

step "Delete a document and wait for the scheduler to purge it"
# The scheduler started with its schedules, the audit checkpoints among them.
stack logs --no-color scheduler | grep '"scheduler.started"' | grep -q '"audit.checkpoint"'
uv run --directory backend python -c   "import sys; from tests.knowledge_samples import pdf; sys.stdout.buffer.write(pdf('Karar 2026/37 kabul edildi.'))"   > "$sample.doomed"
doomed="$(editor -H 'Content-Type: application/octet-stream' --data-binary "@$sample.doomed"   -X POST "$base/api/collections/$collection/documents?filename=Karar%202026-37.pdf" | json "['id']")"
rm -f "$sample.doomed"
wait_parsed "$doomed" 60
editor -X DELETE "$base/api/documents/$doomed"
purged=""
for _ in $(seq 60); do
  left="$(stack exec -T db psql -U postgres -d synapse -Atc     "SELECT count(*) FROM synapse.documents WHERE id = '$doomed'")"
  if [ "$left" = "0" ]; then purged=1; break; fi
  sleep 1
done
[ -n "$purged" ] || { echo "the deleted document was not purged within a minute" >&2; exit 1; }
stack exec -T db psql -U postgres -d synapse -Atc   "SELECT action FROM synapse.audit_events WHERE target_id = '$doomed' ORDER BY seq DESC LIMIT 1"   | grep -qx "kb.document.purge"

if [ -n "$with_models" ]; then
  step "Check the vectors, and the reranker and the chat model through the API's adapters"
  vectors="$(stack exec -T db psql -U postgres -d synapse -Atc \
    "SELECT count(*) FILTER (WHERE c.embedding IS NULL), count(*), min(v.embedded_with)
     FROM synapse.document_chunks c JOIN synapse.document_versions v ON v.id = c.version_id
     WHERE v.document_id IN ('$document', '$scanned')")"
  echo "chunks without a vector, chunks, model: $vectors"
  grep -qE '^0\|[1-9][0-9]*\|bge-m3$' <<<"$vectors"
  stack exec -T api python - <<'PYTHON'
import asyncio, json
from synapse.kernel.config import get_settings
from synapse.models.public import ChatMessage, models_from

async def main() -> None:
    models = models_from(get_settings())
    assert models.reranker and models.chat, "the API has no reranker or chat model"
    scores = await models.reranker.rerank(
        "Belediye meclisi hangi kararı aldı?",
        ["Hava bugün yağmurlu.", "Belediye meclisi 2026/35 sayılı kararı kabul etti."],
    )
    print("rerank scores:", [round(s, 2) for s in scores])
    assert scores[1] > scores[0]
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
    reply = await models.chat.complete(
        [ChatMessage("user", "Kaynak: Karar 2026/35 kabul edildi. Soru: Hangi karar kabul edildi?")],
        schema=schema,
        max_tokens=100,
    )
    print("chat:", reply.content, f"({reply.prompt_seconds} s prompt)")
    assert "2026/35" in json.loads(reply.content)["answer"]
    await models.close()

asyncio.run(main())
PYTHON
fi

step "Check the audit log recorded the sign-in and is intact"
report="$(stack exec -T api synapse audit verify | tail -n 1)"
grep -q '"ok": true' <<<"$report"

if [ -n "$with_backup" ]; then
  # $sample.back holds the first document's file as downloaded, $sample the scanned one's.
  backup_work="$(mktemp -d)"
  as_root() {
    sudo -E synapsectl/.venv/bin/python tools/smoke_backup.py \
      "$backup_work" "$project" "$tenant_id" "$1"
  }
  step "Back the installation up, verify the backup, then remove the installation"
  as_root backup
  # both recorded for the operations page
  runs="$(stack exec -T db psql -U postgres -d synapse -Atc     "SELECT kind || ' ' || ok FROM synapse.operation_runs ORDER BY finished_at")"
  grep -qx "backup true" <<<"$runs"
  grep -qx "backup_verify true" <<<"$runs"
  stack down -v

  step "Restore the backup and start the services again"
  as_root restore
  stack up -d --wait api worker scheduler web "${model_servers[@]}"

  step "Check the documents, their files and the audit log came back"
  csrf="$(sign_in_editor)"
  editor "$base/api/collections/$collection/documents" | grep -q '"title":"Karar 2026-35"'
  editor -o "$sample.restored" "$base/api/documents/$document/versions/1/file"
  cmp "$sample.back" "$sample.restored"
  editor -o "$sample.restored" "$base/api/documents/$scanned/versions/1/file"
  cmp "$sample" "$sample.restored"
  page_query "$document" text | grep -q "Karar 2026/35 kabul edildi."
  page_query "$scanned" text | grep -q "15.03.2026"
  report="$(stack exec -T api synapse audit verify | tail -n 1)"
  grep -q '"ok": true' <<<"$report"

  step "Upload a document to the restored installation"
  # The restored files' directory must be the API's again, or no upload could be stored.
  uv run --directory backend python -c \
    "import sys; from tests.knowledge_samples import pdf; sys.stdout.buffer.write(pdf('Karar 2026/36 kabul edildi.'))" \
    > "$sample"
  after="$(editor -H 'Content-Type: application/octet-stream' --data-binary "@$sample" \
    -X POST "$base/api/collections/$collection/documents?filename=Karar%202026-36.pdf" | json "['id']")"
  wait_parsed "$after" 60
  page_query "$after" text | grep -q "Karar 2026/36 kabul edildi."
  rm -f "$sample.restored"
fi
rm -f "$editor_jar" "$sample" "$sample.back"

step "Smoke test passed"
