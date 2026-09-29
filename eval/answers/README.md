# Answer benchmark

Grounded answers from a local model on the [golden set](../golden/README.md): the Turkish grounded-QA benchmark that ADR 0009 makes the chat model's choice depend on, and the first measurement for phase 4, step 8.

## Method

- A llama.cpp server runs the candidate on the CPU, as the 16 GB tier will (one request at a time, 6 threads, 8,192 tokens of context, thinking off).
- Each question gets six chunks as numbered sources: its evidence chunks among BM25's other top chunks, shuffled (`oracle`: what the model makes of good sources), or the top six of a retrieval run of [eval/retrieval/](../retrieval/README.md) (what it makes of what search finds).
- The model answers as JSON (`answer`, `citations`, `sufficient`) under a grammar the server enforces, told to use the sources only and to say "Belgelerde bulunamadı." when they do not suffice.
- Scored: an answerable question is correct when the answer contains the golden answer (or each answer part), after Turkish lower-casing and plain apostrophes and dashes; an unanswerable one when the model says the sources do not suffice; cited when a cited source holds the evidence. Timings come from the server: prompt tokens and seconds (the time to the first token), tokens generated per second.

## Running it

```bash
docker run -d --name synapse-llm-bench -p 127.0.0.1:8081:8080 -v "$HOME/.cache/huggingface/hub:/hub:ro" \
  ghcr.io/ggml-org/llama.cpp:server -m /hub/<model snapshot>/<file>.gguf -c 8192 -t 6 --parallel 1 --jinja
uv run --directory backend python ../eval/answers/answer.py NAME [--context oracle|RUN] [--limit 75]
```

`eval/answers/work/` is git-ignored. The candidates (ADR 0009, 16 GB CPU tier): Qwen3.5-4B (`unsloth/Qwen3.5-4B-GGUF`, Q4_K_M) and Gemma 4 E4B (`ggml-org/gemma-4-E4B-it-GGUF`, Q4_0), both Apache-2.0.

## Limits

- "Contains the golden answer" misses a correct answer written differently ("2,5 milyon TL" for "2.500.000 TL") and passes one that states it among wrong ones; a sample of answers is read by hand before a result is trusted.
- The golden set's wording favours sources that share its words; the paraphrased copy is not used here yet.
