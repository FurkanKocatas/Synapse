# 0018. Model defaults: bge-m3, bge-reranker-v2-m3 and Qwen3.5-4B on llama.cpp

- Status: accepted (Furkan, 2026-10-01)
- Date: 2026-09-30

## Context

[ADR 0009](0009-model-runtime.md) left the defaults per tier to benchmarks on real hardware, and an ONNX Runtime adapter for encoders to whether it is faster on the CPU; [ADR 0010](0010-rag-pipeline.md) wants the first stage, the reranker and the chat model chosen by measurement. Measured on the reference machine of the 16 GB tier (Ryzen 5 6600H, 16 GB, its integrated Radeon 680M) with the golden set and its paraphrased copy: [benchmarks/embeddings.md](../benchmarks/embeddings.md) (retrieval, encoders and their cost) and [benchmarks/answers.md](../benchmarks/answers.md) (the chat models).

What the measurements say:

- bge-m3 is the best encoder by a wide margin on questions not worded like the source (Hit@10 0.86 against 0.76 for the next, e5-base), but costs 3.4 times e5-base on the CPU.
- A cross-encoder reranker adds 7 to 18 points of Hit@1 on every first stage, but takes 8 seconds per question on the CPU against a budget of 3.
- llama.cpp runs both encoders faster than ONNX Runtime and PyTorch on the CPU (bge-m3 1.7 times, the reranker 1.6), and on a GPU through Vulkan, which current integrated GPUs support: on the reference machine's integrated GPU bge-m3 embeds 3.4 times as fast as on ONNX Runtime and the reranker takes 2.5 seconds, with the same rankings over the whole golden set.
- ONNX Runtime's int8 is not usable on a CPU with AVX2 but no VNNI; llama.cpp's 8-bit weights on the GPU cost nothing.
- Qwen3.5-4B answers 0.85 to 0.86 of the answerable questions correctly against Gemma 4 E4B's 0.71 to 0.77, with half the false refusals and no broken outputs, within the latency budget on the CPU alone and 2.6 times faster to the first token on the integrated GPU.

## Decision

**One engine.** llama.cpp `llama-server` serves chat, embeddings and reranking, three instances as ADR 0009 describes; no ONNX Runtime adapter. The installer picks the image by hardware: `server-vulkan` with the GPU passed through (`/dev/dri`) when a Vulkan device is found, integrated or not, `server` otherwise, both at the same pinned build. The same model files serve both.

**Models** (all allowed by ADR 0016 without review):

| Role | Model | Licence | Weights |
|---|---|---|---|
| Embedding | BAAI/bge-m3, dense vectors, 1,024 dimensions, 512 tokens | MIT | 8-bit (Q8_0) on a GPU, 16-bit on the CPU |
| Reranking | BAAI/bge-reranker-v2-m3 | Apache-2.0 | 8-bit (Q8_0) on a GPU, 16-bit on the CPU |
| Chat, 16 GB tier | Qwen3.5-4B | Apache-2.0 | Q4_K_M |

Encoders are converted from pinned Hugging Face revisions with llama.cpp's own converter at the pinned build; each file's SHA-256 is recorded in `docs/licences.md` with the rest of the bundle. Encoder servers run with batches of 512 tokens (llama.cpp computes attention over a whole batch's texts at once). The chat server runs with thinking off (`--reasoning-budget 0`).

**Query path on these models:** BM25 (PostgreSQL's `turkish` configuration on text lower-cased with `turkish.lower`, identifiers indexed whole) and bge-m3 vectors, each over chunks with their document context in front, fused by reciprocal rank; the fusion's top 15 reranked. The fused order is shown at once, the reranked order replaces it when it arrives (3.8 s on the reference machine's integrated GPU). On both question sets this reaches the best of either first stage: Hit@1 0.76 and Hit@10 0.97 as written, 0.60 and 0.86 paraphrased.

## Consequences

- One model format, one engine and one API for every model; an encoder change is a file and a flag.
- The index stores bge-m3's 1,024-dimensional vectors (4 KB per chunk at 32 bits, half at 16), and every document is embedded again if the encoder ever changes.
- On a machine with a usable GPU, 100,000 chunks embed in about 6.3 hours (one night) and the reranker fits the 3-second budget. On the CPU alone they take about 12.6 hours, more than a night (ingestion is resumable), and the reranker takes about 5 seconds: there the sources appear in the first stage's order within the budget and are reordered when the reranker returns.
- The installer must detect a Vulkan device, pass it into the containers and check at `doctor` time that the GPU backend actually loaded, falling back to the CPU image when it did not.
- Memory on the 16 GB tier: the chat server about 4.2 GB; each encoder server about 1.2 GB on the integrated GPU (which has no memory of its own: it is system memory too) and 0.3 GB for its process.

## Alternatives considered

- **multilingual-e5-base on ONNX Runtime:** 3.4 times cheaper on the CPU, 10 points lower Hit@10 on paraphrased questions; the gap the encoder exists to close.
- **ONNX Runtime for the encoders (ADR 0009's option):** slower than llama.cpp on the same CPU, no GPU path on this hardware without another runtime, and its int8 is unusable without VNNI.
- **No reranker on the CPU tier:** 7 to 18 points of Hit@1 lost; showing sources before reranking keeps the budget without losing them.
- **Gemma 4 E4B:** 8 to 15 points fewer correct answers, twice the false refusals, broken outputs under a JSON schema; better only on multi-document questions.
- **Cutting reranker inputs to 256 or 384 tokens:** 20 or 1 points of Hit@1 lost for 53 or 28 percent less time; the GPU makes it unnecessary.
