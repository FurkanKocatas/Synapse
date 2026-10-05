#!/usr/bin/env bash
# End-to-end check of the full stack built from this repository: fresh database, bootstrap,
# migrations, a tenant and an account created with the CLI, then a sign-in through the web
# front. Runs in its own compose project and removes everything it created when it exits.
#
# Usage: tools/stack_smoke.sh                      (needs Docker; used by CI)
#        tools/stack_smoke.sh --with-models [--vulkan]
#
# --with-models also starts the model servers (ADR 0018) from the files in SYNAPSE_MODELS_DIR
# (default .dev/models; synapsectl models fetch): documents must reach "ready" with their
# vectors, and the API's own adapters must get answers from the reranker and the chat model.
# --vulkan runs them on the GPU (deploy/compose.vulkan.yml). CI has no model files.

set -euo pipefail
cd "$(dirname "$0")/.."

with_models="" vulkan=""
for argument in "$@"; do
  case "$argument" in
    --with-models) with_models=1 ;;
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

step "Start the API, the worker and the web front${with_models:+, and the model servers}"
stack up -d --wait api worker web "${model_servers[@]}"

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
rm -f "$editor_jar" "$sample" "$sample.back"

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

step "Smoke test passed"
