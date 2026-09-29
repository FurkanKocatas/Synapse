# Retrieval benchmark

Measures retrieval on the [golden set](../golden/README.md): lexical, dense (the embedding bake-off of [phase 4](../../docs/plan/phase-4.md), step 6) and fused rankings over the corpus as ingestion chunks it. Results: [docs/benchmarks/embeddings.md](../../docs/benchmarks/embeddings.md).

## Method

- **Chunks** ([chunks.py](chunks.py)): every corpus document the light parser reads, its pages that pass the page quality check, cut by the product's chunker; each chunk is indexed as `indexed_text` (heading path, then text). `--parser docling` builds the same from Docling's blocks (with the text layer for pages where Docling keeps less than 0.99 of the words), for the comparison proposed in [docs/benchmarks/parsing.md](../../docs/benchmarks/parsing.md).
- **Embeddings** ([embed.py](embed.py)): each candidate model embeds every chunk and every question, with the prefixes its model card prescribes, 512 tokens at most, on the CPU. It records the time for the corpus, the time for one question alone and the peak memory.
- **Scoring** ([score.py](score.py)): a question is found at rank k when the top k chunks cover every piece of its evidence (a chunk from the evidence's document whose pages include the evidence's page or one of its `also` pages). Hit@1, Hit@10 and MRR@10, per question type. Unanswerable questions are left out: refusing them is the answer step's job, measured there.

## Running it

```bash
uv run --directory backend python ../eval/retrieval/chunks.py                    # work/chunks-light.jsonl
uv sync --project eval/retrieval                                                 # sentence-transformers, CPU PyTorch
uv run --project eval/retrieval python eval/retrieval/embed.py e5-base           # one model; see MODELS in embed.py
uv run --directory backend python ../eval/retrieval/score.py [--misses RUN]
```

`eval/retrieval/work/` is git-ignored. Models download from Hugging Face on first use; `embed.py` records the revision it used.

## Limits

- The golden set's questions were drafted from the same page texts the chunks come from; its wording is paraphrased, but lexical overlap with the source is likely higher than with real users' questions, which favours BM25.
- A multi-document question needs two chunks, so its Hit@1 is 0 by definition; use its Hit@10.
- The candidates run under PyTorch here in full precision; the product's runtime (llama.cpp or ONNX Runtime, ADR 0009) changes the speed, and quantised weights can move rankings a little, so the chosen model is measured again on it.
