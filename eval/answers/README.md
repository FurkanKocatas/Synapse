# Answer benchmark

Grounded answers from a local model on the [golden set](../golden/README.md): the Turkish grounded-QA benchmark that ADR 0009 makes the chat model's choice depend on, and the first measurement for phase 4, step 8.

## Method

- A llama.cpp server runs the candidate on the reference machine's integrated GPU through Vulkan, and on its CPU alone for timings (one request at a time, 6 threads on the CPU, 8,192 tokens of context). Thinking is off on the server (`--reasoning-budget 0`): with a JSON schema, Gemma 4 otherwise thinks in plain text whatever `enable_thinking` says, and runs out of tokens before the JSON.
- Each question gets six chunks as numbered sources: its evidence chunks among BM25's other top chunks, shuffled (`oracle`: what the model makes of good sources), or the top six of a retrieval run of [eval/retrieval/](../retrieval/README.md) (what it makes of what search finds).
- The model answers as JSON (`answer`, `citations`, `sufficient`) under a grammar the server enforces, told to use the sources only and to say "Belgelerde bulunamadı." when they do not suffice.
- Scored: an answerable question is correct when the answer contains the golden answer (or each answer part), after Turkish lower-casing, plain apostrophes and dashes, and numbers written as digits ([numerals.py](../../backend/src/synapse/chat/numerals.py), shared with the product's answer verification: "üç yıl" and "3 yıl", "302.250.000" and "302250000", "dokuz yüz yirmi bin" and "920000" agree); an unanswerable one when the model says the sources do not suffice; cited when a cited source holds the evidence. Timings come from the server: prompt tokens and seconds (the time to the first token), tokens generated per second.

## Running it

```bash
docker run -d --name synapse-llm-bench --device /dev/dri -p 127.0.0.1:8081:8080 -v "$HOME/.cache/huggingface/hub:/hub:ro" \
  ghcr.io/ggml-org/llama.cpp:server-vulkan-b11243 -m /hub/<model snapshot>/<file>.gguf -c 8192 --parallel 1 --jinja \
  -ngl 99 --reasoning-budget 0
uv run --directory backend python ../eval/answers/answer.py NAME [--context oracle|RUN] [--limit 75]
```

On the CPU alone: the image `server`, and `-t 6` in place of `--device /dev/dri` and `-ngl 99`. `eval/answers/work/` is git-ignored. The candidates (ADR 0009, 16 GB CPU tier): Qwen3.5-4B (`unsloth/Qwen3.5-4B-GGUF`, Q4_K_M) and Gemma 4 E4B (`ggml-org/gemma-4-E4B-it-GGUF`, Q4_0), both Apache-2.0.

## Through the product

Two scripts ask the golden set through a running stack's API instead of a bare model server: the stack of [eval/retrieval/product.py](../retrieval/README.md), with the corpus uploaded and the model servers running (`SYNAPSE_STACK_MODELS=1`).

- [refusal.py](refusal.py): every question through `POST /api/search`, reranked; its best reranker score, and whether the evidence was among the hits. Prints the scores' spread for answerable and unanswerable questions and, per threshold, how many of each refusal before generation would refuse. Writes `work/refusal-<questions>.jsonl`.
- [chat.py](chat.py): every question through `POST /api/chat`, each in a conversation of its own, as the page asks it: search, refusal, the context, the streamed answer, verification. Scored like answer.py (correct, cited, refused), with the time to the sources, to the first token and to the whole answer as the client sees them. With `--scores` (refusal.py's output) it also prints what each threshold of refusal before generation would make of these answers; for that the API runs with `SYNAPSE_CHAT_REFUSE_BELOW=-100`, so every question reaches the model. Writes `work/chat-<questions>.jsonl`.

```bash
uv run --directory backend python ../eval/answers/refusal.py --base http://127.0.0.1:8490 \
  --email editor@golden.example --password-file "$PWD/.dev/golden-password"
uv run --directory backend python ../eval/answers/chat.py --base http://127.0.0.1:8490 \
  --email editor@golden.example --password-file "$PWD/.dev/golden-password" \
  --scores "$PWD/eval/answers/work/refusal-questions.jsonl"
```

Results: [docs/benchmarks/refusal.md](../../docs/benchmarks/refusal.md) and [answers.md](../../docs/benchmarks/answers.md#in-the-product).

## Hand scoring

Results: [docs/benchmarks/answers.md](../../docs/benchmarks/answers.md). There, every answer the script scored wrong (before numerals.py) was read by hand; these state the golden answer and count as correct (2026-09-30, 75 questions, seed 7):

| Run | Re-scored as correct |
|---|---|
| `qwen3.5-4b-q4km`, oracle | g5-15, g5-03, g6-11, g6-08, g2-07, g2-04, g2-11, g1-01, g5-11, g8-24, g7-06 |
| `qwen3.5-4b-q4km`, `bm25-prefix5+bge-m3-reranker@10` | g5-15, g5-03, g2-19, g6-02, g6-11, g6-08, g2-07, g8-08, g2-04, g2-11, g5-21, g1-01, g5-11, g8-24 |
| `gemma-4-e4b-q4`, oracle | g5-03, g6-08, g8-24 |
| `gemma-4-e4b-q4`, `bm25-prefix5+bge-m3-reranker@10` | g5-03, g1-04 |

## Limits

- "Contains the golden answer" misses a correct answer worded differently ("en az 3, en fazla 5 üyeden" for "en az üç en fazla beş kişiden", "2,5 milyon TL" for "2.500.000 TL") and passes one that states it among wrong ones; answers are read by hand before a result is trusted.
- The golden set's wording favours sources that share its words; the paraphrased copy is not used here yet.
