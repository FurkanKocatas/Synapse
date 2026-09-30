# Retrieval benchmark

Measures retrieval on the [golden set](../golden/README.md): lexical, dense (the embedding bake-off of [phase 4](../../docs/plan/phase-4.md), step 6) and fused rankings over the corpus as ingestion chunks it. Results: [docs/benchmarks/embeddings.md](../../docs/benchmarks/embeddings.md).

## Method

- **Chunks** ([chunks.py](chunks.py)): every corpus document the light parser reads, its pages that pass the page quality check, cut by the product's chunker; each chunk is indexed as `indexed_text` (heading path, then text). `--parser docling` builds the same from Docling's blocks (with the text layer for pages where Docling keeps less than 0.99 of the words), for the comparison proposed in [docs/benchmarks/parsing.md](../../docs/benchmarks/parsing.md).
- **Embeddings** ([embed.py](embed.py)): each candidate model embeds every chunk and every question, with the prefixes its model card prescribes, 512 tokens at most, on the CPU, under PyTorch, on ONNX Runtime in full precision or with 8-bit weights ([onnx_encoder.py](onnx_encoder.py), what the product's ONNX Runtime adapter would do), or as GGUF on a llama.cpp server, on the CPU or on a GPU through Vulkan ([llama_encoder.py](llama_encoder.py), below). `--speed N` times a fixed sample, with nothing else running, since a whole corpus takes up to hours per model.
- **Reranking** ([rerank.py](rerank.py)): a cross-encoder reorders a run's top candidates, on the same backends.
- **Scoring** ([score.py](score.py)): a question is found at rank k when the top k chunks cover every piece of its evidence (a chunk from the evidence's document whose pages include the evidence's page or one of its `also` pages). Hit@1, Hit@10 and MRR@10, per question type. Unanswerable questions are left out: refusing them is the answer step's job, measured there.

## Running it

```bash
uv run --directory backend python ../eval/retrieval/chunks.py                    # work/chunks-light.jsonl
uv sync --project eval/retrieval                                                 # sentence-transformers, CPU PyTorch
uv run --project eval/retrieval python eval/retrieval/embed.py e5-base           # one model; see MODELS in embed.py
uv run --project eval/retrieval python eval/retrieval/embed.py e5-base --backend onnx-int8 --speed 256
uv run --directory backend python ../eval/retrieval/score.py [--misses RUN]
```

On llama.cpp, the model is converted once from the same Hugging Face revision with llama.cpp's `convert_hf_to_gguf.py` (at the server image's build), and served on this machine; texts are tokenized by the script with the model's own tokenizer and cut to the same length as on the other backends:

```bash
python llama.cpp/convert_hf_to_gguf.py <snapshot of BAAI/bge-m3> --outtype q8_0 --outfile gguf/bge-m3-q8_0.gguf
docker run -d --device /dev/dri -p 127.0.0.1:8082:8080 -v $PWD/gguf:/models:ro \
  ghcr.io/ggml-org/llama.cpp:server-vulkan-b11243 -m /models/bge-m3-q8_0.gguf --embedding --pooling cls \
  -ngl 99 -c 8192 -np 16 -b 512 -ub 512
uv run --project eval/retrieval python eval/retrieval/embed.py bge-m3 --backend llama --label vulkan-q8_0
```

The reranker the same way, with `--reranking -c 6144 -np 10` in place of `--embedding --pooling cls -c 8192 -np 16`, at port 8083 (`rerank.py --backend llama`). Batches of 512 tokens are fastest: llama.cpp computes attention over a whole batch's texts at once. On the CPU alone: the image `server`, `--outtype f16` (faster there than Q8_0), and `-t 6` in place of `--device /dev/dri` and `-ngl 99`.

`eval/retrieval/work/` is git-ignored. Models download from Hugging Face on first use; `embed.py` records the revision it used.

## Limits

- The golden set's questions were drafted from the same page texts the chunks come from; its wording is paraphrased, but lexical overlap with the source is likely higher than with real users' questions, which favours BM25.
- A multi-document question needs two chunks, so its Hit@1 is 0 by definition; use its Hit@10.
- Quantised weights move rankings a little; the chosen model is measured again on the runtime the product uses.
