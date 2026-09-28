# 02 Hardware and Local Inference

Research date: 2026-09-28. Scope: what Synapse can run on a CPU-only AMD Ryzen 5 3600 (6C/12T, Zen 2, AVX2, no AVX-512) with 16 to 32 GB DDR4, and what an optional GPU buys. Documents and questions are mostly Turkish; target is up to ~10,000 documents (~40-60k chunks) and 5-10 concurrent users on the CPU tier.

## 0. How to read the numbers

Every number is tagged:

- **[M]** measured by a third party, with hardware, quant and source given.
- **[E]** our estimate, with the method stated. Estimates for the Ryzen 5 3600 are derived from (a) measured numbers on comparable Zen 2/Zen 3 DDR4 machines and (b) first-principles limits: token generation (tg) is memory-bandwidth bound, prompt processing (pp, prefill) is compute bound.

Reference limits for the Ryzen 5 3600 with dual-channel DDR4-3200: theoretical bandwidth 51.2 GB/s, practically ~35-40 GB/s usable by llama.cpp; AVX2 FP32 peak ~700 GFLOPS across 6 cores, realistically 150-300 GFLOPS sustained in inference kernels. A SpecPicks test on a 12-core Zen 2 Ryzen 9 3900X showed that raising RAM from DDR4-2666 to DDR4-3600 lifted generation 34% (6.32 to 8.45 tok/s) while prefill stayed flat at ~69 tok/s (Mistral 7B Q6_K, llamafile) [M] (https://specpicks.com/reviews/ryzen-5-2600-vs-ryzen-9-3900x-cpu-only-qwen3-8b-2026, 2026). Practical consequence: **on the CPU tier, fast RAM helps generation, more cores help prefill, and prefill is the bottleneck for RAG.**

## 1. Inference runtimes

| Runtime | CPU perf on AVX2 | Concurrency | OpenAI API | Embeddings / rerank | GPU fallback | License | Docker packaging | Verdict |
|---|---|---|---|---|---|---|---|---|
| **llama.cpp (llama-server)** | Reference for GGUF on CPU; best-maintained AVX2 kernels | `--parallel N` slots + continuous batching (`--cont-batching`), prompt cache per slot | Yes (`/v1/chat/completions`, `/v1/completions`) | Yes: `--embedding` (`/v1/embeddings`) and `--reranking` (`/v1/rerank`) | CUDA, Vulkan, ROCm/HIP, SYCL, Metal | MIT | Official images per backend (cpu, cuda, vulkan, rocm) | **Default** |
| Ollama | Wraps llama.cpp-derived engine; lags upstream on new architectures (issue: Qwen3.5 much slower than llama.cpp, https://github.com/ollama/ollama/issues/14579, 2026) | `OLLAMA_NUM_PARALLEL`, model load/unload manager | Yes | Embeddings yes; server-side rerank work only reported in 2026 digests (https://github.com/kakapez/agents-radar/issues/1620, 2026-09-28) | CUDA, ROCm, Vulkan (experimental since 0.12.6, https://www.phoronix.com/news/ollama-Experimental-Vulkan) | MIT | Trivial | Good for dev; less control for product |
| vLLM (CPU backend) | AVX-512 recommended; AVX2 "supported with limited features" (https://docs.vllm.ai/en/stable/getting_started/installation/cpu/, 2026); AVX2 INT4 MoE fallback only just added (https://github.com/vllm-project/vllm/pull/58614) | Excellent (paged attention, continuous batching) | Yes | Yes (pooling models) | CUDA, ROCm (its real home) | Apache 2.0 | Heavy images | **GPU tier only**, not Ryzen 5 3600 |
| OpenVINO Model Server | Good on x86 AVX2 including AMD (CPU plugin is ISA-based), strongest on Intel | Continuous batching + paged attention on CPU (https://docs.openvino.ai/2026/model-server/ovms_demos_continuous_batching.html) | Yes (chat, completions, responses) | Yes: embeddings (OpenAI style) and rerank (Cohere style) (https://medium.com/openvino-toolkit/rag-building-blocks-made-easy-and-affordable-with-openvino-model-server-e7b03da5012b) | Intel GPU/NPU only, no CUDA | Apache 2.0 | Official images | Serious alternative for embeddings/rerank; benchmark on AMD |
| ONNX Runtime GenAI | Decent INT4 CPU path | No production server; library only | No (only via third-party wrappers) | ORT itself is the standard for encoder embeddings | CUDA, DirectML | MIT | DIY | Use plain ORT for embeddings, not GenAI for LLM |
| MLC LLM | CPU is not its focus | Server with batching | Yes | Limited | CUDA, Vulkan, ROCm, Metal | Apache 2.0 | DIY | Skip |
| ik_llama.cpp | Faster pp in its own benchmarks (Zen 4 7950X, AVX2 path: 1.8x to 3.6x pp on Llama-3.1-8B depending on quant, https://github.com/ikawrakow/ik_llama.cpp/discussions/164) but a user on Ryzen 7 5800X measured it **2x slower pp, 1.5x slower tg** than mainline on a Qwen3.6-35B-A3B MoE (https://github.com/ikawrakow/ik_llama.cpp/issues/1699, 2026-04-27) | Same server model as llama.cpp | Yes | Partial | CUDA (Turing+) mainly | MIT | DIY builds | Benchmark only; fork risk |
| LocalAI | Wraps llama.cpp and others | Inherits backends | Yes (broad) | Yes | Inherits | MIT | Good images | Extra layer we do not need |

Key points:

- **llama-server gives one binary, one API style and one model format (GGUF) for chat, embeddings and rerank**, on CPU and on every GPU vendor. That is the simplest thing to package and support at 50+ on-prem sites.
- vLLM is the right engine only when there is a CUDA GPU and >10 concurrent users. Its CPU backend targets AVX-512/AMX Xeons.
- Ollama is convenient but adds a model manager we would fight (auto unload, different flags, delayed support for new model architectures).

## 2. LLM choice for Turkish on CPU

### 2.1 Candidate models (2025-2026)

| Model | Type | Params total / active | Approx Q4_K_M size | Released | License | Notes |
|---|---|---|---|---|---|---|
| Qwen3.5-4B | dense (hybrid attention) | 4B | ~2.8 GB [E] | 2026-03-02 | Apache 2.0 | 201 languages, 262K ctx, vision (https://artificialanalysis.ai/articles/qwen3-5-small-models) |
| Qwen3.5-9B | dense (hybrid attention) | 9B | ~5.8 GB [E] | 2026-03-02 | Apache 2.0 | Turkish fine-tune exists (Mergen-TR) |
| Qwen3-30B-A3B (2507) | MoE | 30.5B / 3.3B | 18.6 GB | 2025 | Apache 2.0 | Most CPU data available |
| Qwen3.5-35B-A3B / Qwen3.6-35B-A3B | MoE | 35B / ~3B | ~21 GB; Unsloth quotes 23 GB total memory at Q4_K_XL (https://unsloth.ai/docs/models/qwen3.6) | 2026-02-24 / 2026 | Apache 2.0 (3.5) | Best quality per CPU-second if RAM allows |
| Gemma 4 E4B | dense, per-layer embeddings | ~4B effective | ~5 GB [E] | 2026-04-02 | Gemma terms | 140+ languages (https://huggingface.co/google/gemma-4-E4B) |
| Gemma 4 26B-A4B | MoE | 26B / 4B | 16-18 GB (https://www.starryhope.com/minipcs/gemma-4-on-mini-pcs/) | 2026-04-02 | Gemma terms | Gemma family is strong in Turkish (see 2.3) |
| Phi-4-mini | dense | 3.8B | ~2.5 GB | 2025 | MIT | Weak multilingual history; low priority |
| Llama 3.2 3B / 3.1 8B | dense | 3B / 8B | 2 / 4.9 GB | 2024 | Llama license | Superseded; Llama 4 has no small size |
| Mistral Small 3.x | dense | 24B | ~14 GB | 2025 | Apache 2.0 | Too slow dense on CPU |
| Trendyol-LLM-8B-T1 | dense (Turkish tuned) | 8B | ~5 GB | 2025 | check model card | Best in a 2026 Turkish doc-QA study (2.3) |
| Kumru-2B (VNGRS) | dense, Turkish from scratch | 2B | ~1.3 GB | 2025 | Apache 2.0 | Weak on TurkBench (27.3%) |
| Turkcell-LLM-7b, Cosmos Turkish-Llama-8B, TR-Gemma-9b | Turkish tuned | 7-9B | 4-6 GB | 2024-2025 | varies | Older bases |
| TÜBİTAK BİLGEM BILGE | Turkish foundation | n/a | n/a | announced 2026-06 | not open | Not usable yet (https://dastechno.com/yapay-zeka/yerli-yapay-zeka-modelleri-turkiye/) |

### 2.2 CPU speed evidence

Measured data points on comparable DDR4 hardware:

| Hardware | Model / quant | pp tok/s | tg tok/s | Source |
|---|---|---|---|---|
| Ryzen 5 5600U (6C Zen 3, DDR4-3200) | Qwen3-30B-A3B Q4_K_XL | 57.6 (102-token prompt) | 16.1 [M] | llama.cpp #13217 via SpecPicks, https://specpicks.com/reviews/ryzen-5-2600-vs-ryzen-7-5800x-cpu-only-qwen3-30b-a3b-2026 (2026-09-25) |
| Ryzen 7 8840U, CPU AVX2 path | Qwen3-30B-A3B Q4_K_M | n/a | ~15 [M] | https://github.com/ggml-org/llama.cpp/issues/13217 (2025-04-30) |
| Ryzen 9 3900X (12C Zen 2, DDR4-3200) | Mistral 7B Q6_K | ~69 | 7.55 [M] | llamafile #450, https://github.com/mozilla-ai/llamafile/discussions/450 |
| Ryzen 5 5600X (6C Zen 3, DDR4-3000) | Mistral 7B Q4_0 | 23.9 (pp256) | 8.95 [M] | same |
| Ryzen 7 5800X + GTX 1660 Super 6 GB, MoE experts on CPU | Qwen3.6-35B-A3B IQ4_XS | 239.8 | 15.7 [M] | https://github.com/ikawrakow/ik_llama.cpp/issues/1699 (2026-04-27) |
| Zen 5 HX 370, DDR5-5600 | Qwen3-Coder-Next 80B-A3B Q4_K_M | n/a | 7.7 (expected 20-30) [M] | https://github.com/ggml-org/llama.cpp/issues/19480 (2026-02-10) |

The last row is a warning: **the Qwen3-Next style hybrid architecture (gated DeltaNet, which Qwen3.5 inherits) had CPU kernels that ran 3-4x below the bandwidth limit in early 2026.** Qwen3.5 speed on our CPU must be measured, not assumed.

Estimates for the Ryzen 5 3600, DDR4-3200 dual channel, llama.cpp, 6 threads, Q4_K_M [E]:

| Model | RAM for weights | pp tok/s | tg tok/s | Fits 16 GB system? |
|---|---|---|---|---|
| Qwen3.5-4B / Gemma 4 E4B | 3-5 GB | 60-90 | 10-14 | Yes |
| Qwen3.5-9B / Trendyol-8B | 5-6 GB | 25-40 | 5-7 | Yes, tight with the rest of the stack |
| Qwen3-30B-A3B / Qwen3.5-35B-A3B | 19-21 GB (+KV) | 45-80 | 12-16 | **No, needs 32 GB** |
| Gemma 4 26B-A4B | 16-18 GB | 35-60 | 9-12 | No, needs 32 GB |

Method: tg = usable bandwidth / bytes read per token (active weights at ~4.9 bits/weight), cross-checked with the 5600U and 8840U MoE measurements; pp scaled from the 3900X dense result by core count (6 vs 12) and active parameter count.

**MoE advantage:** a 30-35B MoE with ~3B active parameters generates about as fast as a 3-4B dense model while giving 30B-class answers, because only the active experts are read from RAM per token. Prefill gains less (MoE matmuls batch poorly on CPU), and the full weights must still sit in RAM, which is why MoE is a 32 GB feature.

### 2.3 Turkish quality evidence

| Benchmark | Finding | Source |
|---|---|---|
| TurkBench (27 open models) | gemma-3-12b-it 71.0%, gemma-3-12b-TR-V1 71.2%, TR-Gemma-9b 65.3%, Llama-3.1-8B-Instruct 45.7%, Qwen3-1.7B 36.5%, TDM-8b 30.0%, Kumru-2B 27.3%. Larger models (Qwen-32B, Gemma-27B) lead; Turkish-language prompts beat English prompts | https://arxiv.org/html/2601.07020v1 (2026-01) |
| Cetvel (33 models, EACL 2026) | Llama-3.3-70B best overall; Turkish-centric instruction models generally underperform multilingual general models | https://arxiv.org/pdf/2508.16431 (2025-08) |
| Turkish domain doc-QA, Q4_K_M on RTX 3050 6 GB, 4K ctx | Trendyol-LLM-8B-T1 75%, Qwen2.5-7B 65%, Cosmos-8B 54%, Mistral-7B 51%, Kocdigital-8B 49%. Trendyol mean latency 23.9 s vs Qwen2.5 1.7 s (it reasons at length). Retrieval: BM25 65% evidence recall vs E5-base 59%, not significantly different | https://arxiv.org/html/2609.28007v1 (2026-09-23) |
| Turkish-MMLU leaderboard | Mergen-TR-Qwen3.5-9B 74.3 (self-reported, ahead of Qwen3-14B and Llama-3.1-70B) | https://huggingface.co/dogukanvzr/Mergen-TR-Qwen3.5-9B (2026) |

Conclusions: (1) No independent Turkish benchmark yet covers Qwen3.5/3.6 or Gemma 4; we must run our own. (2) Gemma models have consistently been the strongest small models on Turkish; Qwen improves quickly and a Turkish Qwen3.5-9B fine-tune scores well. (3) Turkish fine-tunes of older bases (Kumru, TDM, Cosmos) are not competitive; the exception is Trendyol-8B-T1 on grounded QA, at a large latency cost that is prohibitive on CPU. (4) For RAG, faithfulness to context and abstention matter more than trivia scores; the doc-QA study above measures exactly that and should be our template.

### 2.4 End-to-end RAG latency on the Ryzen 5 3600 [E]

Scenario: 3,000-token prompt (system + retrieved chunks + question), 300-token answer, single user, no thinking mode. Turkish tokenizes at roughly 1.3-1.6x more tokens per word than English on Qwen/Gemma tokenizers, so 3,000 tokens is only ~6-8 chunks.

| Model | Prefill | Generation | Time to first token | Total |
|---|---|---|---|---|
| Qwen3.5-4B / Gemma 4 E4B | 33-50 s | 21-30 s | 35-50 s | **55-80 s** |
| Qwen3.5-9B | 75-120 s | 43-60 s | 75-120 s | 2-3 min |
| Qwen3.5-35B-A3B (32 GB) | 38-67 s | 19-25 s | 40-70 s | **60-90 s** |
| Gemma 4 26B-A4B (32 GB) | 50-85 s | 25-33 s | 50-85 s | 75-120 s |
| Any of the above + 6-8 GB GPU with MoE offload | 10-15 s (pp ~240 as measured on 5800X + GTX 1660S) | ~20 s | ~12 s | ~30-35 s |

Levers that matter more than model choice on CPU:

- **Cut the context.** 1,500 tokens instead of 3,000 halves time to first token. Retrieval precision (hybrid search, reranking of fewer candidates, chunk trimming) directly buys latency.
- **Prompt cache.** Keep the system prompt identical and first in the prompt so llama-server reuses its KV cache; follow-up questions in the same conversation only prefill new tokens.
- **Disable thinking mode** on Qwen3.5 by default; reasoning tokens at 10-14 tok/s are unaffordable.
- **Stream** the answer so users see progress after the first token.

### 2.5 Concurrency on CPU [E]

Prefill uses all cores; two simultaneous prefills each run at half speed. Decode is bandwidth bound, so batching several decoding users costs little extra (aggregate tg of 2-4 parallel slots is roughly 1.5-2.5x single-stream), but prefill does not batch for free. Queueing model: 10 active users asking one question every 5 minutes = 2 questions/min; at ~60-80 s service time the server is ~100% utilized and queues build. Realistic CPU-tier promise:

- **5-10 named users, 1-2 simultaneous answers**, `--parallel 2`, a visible queue position, answers in 1-2 minutes, up to 3-4 minutes at peaks.
- Indexing (OCR, embeddings) must be paused or niced during working hours because it competes for the same 6 cores.
- 10 genuinely simultaneous users need the GPU tier.

## 3. Embeddings for Turkish on CPU

### 3.1 Quality

TR-MTEB (26 datasets, EMNLP Findings 2025, https://aclanthology.org/2025.findings-emnlp.471/), Mean(Task) and Retrieval scores:

| Model | Params | Dim | TR-MTEB mean | Retrieval | License |
|---|---|---|---|---|---|
| multilingual-e5-large | 560M | 1024 | 66.82 | 60.62 | MIT |
| text-embedding-3-small (API, reference) | n/a | 768 | 66.61 | 64.99 | proprietary |
| multilingual-e5-large-instruct | 560M | 1024 | 65.92 | 57.21 | MIT |
| gte-multilingual-base | 305M | 1024 | 64.49 | 57.51 | Apache 2.0 |
| multilingual-e5-base | 278M | 768 | 64.26 | 58.29 | MIT |
| multilingual-e5-small | 118M | 384 | 62.53 | 56.53 | MIT |
| paraphrase-multilingual-mpnet-base-v2 | 278M | 768 | 61.71 | 49.27 | Apache 2.0 |

Additional 2026 evidence:

- EmbeddingGemma-300M scores 65.2 on TR-MTEB, turkish-e5-large 66.0, a 200M Turkish-distilled model 63.9 (https://arxiv.org/html/2605.29992, 2026-05).
- On a Turkish retrieval leaderboard, bge-m3 reaches 99.54% of EmbeddingGemma-300M's score, and the 155M Turkish Mecellem encoder 92.36% (https://arxiv.org/abs/2601.16018, 2026-01).
- PosIR Turkish subset: bge-m3 nDCG@1 0.34 vs Qwen3-Embedding-0.6B 0.30 (https://arxiv.org/pdf/2601.08363, 2026).
- jina-embeddings-v3 is CC BY-NC 4.0: excluded for a commercial product.
- The Turkish doc-QA study found BM25 on par with E5-base for evidence recall (65% vs 59%) (https://arxiv.org/html/2609.28007v1). **Hybrid BM25 + dense is mandatory for Turkish**; agglutinative morphology favours lexical matching with a proper Turkish analyzer.

### 3.2 CPU throughput and indexing time [E]

No credible published CPU throughput exists for bge-m3 or Qwen3-Embedding on a 6-core desktop (the Bekko paper explicitly did not measure bge-m3 on x86, https://arxiv.org/pdf/2607.25180). One anchor: multilingual-e5-small at 226 docs/s on an x86 server CPU with OpenVINO, batch 64, 512 max tokens [M] (same paper). INT8 quantization speeds up CPU encoders 3.2x (ONNX) to 5.3x (OpenVINO) with under 0.5% quality loss [M] (https://sbert.net/docs/sentence_transformer/usage/efficiency.html).

Estimates for the Ryzen 5 3600, INT8 ONNX/OpenVINO, 50,000 chunks x ~350 tokens = 17.5M tokens. Method: 2 x non-embedding parameters FLOPs per token at 150-300 effective GFLOPS, x2-3 for INT8, attention overhead included loosely.

| Model | Est. tokens/s | Est. chunks/s | Index 50k chunks |
|---|---|---|---|
| multilingual-e5-small | 3,000-6,000 | 9-17 | **50-100 min** |
| multilingual-e5-base / EmbeddingGemma-300M | 800-1,500 | 2.3-4.3 | **3.3-6 h** |
| bge-m3 / multilingual-e5-large | 300-600 | 0.9-1.7 | 8-16 h |
| Qwen3-Embedding-0.6B (GGUF Q8) | 250-500 | 0.7-1.4 | 10-19 h |

Query-time embedding of a single question is 50-300 ms for all of these, so the choice is about indexing time and quality. For 10,000 documents, e5-base or EmbeddingGemma-300M indexes overnight on CPU; bge-m3 needs a weekend or a GPU (on a 16 GB GPU the same job takes minutes). EmbeddingGemma uses the Gemma terms of use, not an OSI license; e5 and bge-m3 are MIT.

## 4. Rerankers on CPU

| Model | Params | License | Multilingual note |
|---|---|---|---|
| bge-reranker-v2-m3 | 568M (XLM-R large) | Apache 2.0 | Multilingual BEIR avg 69.32 (https://arxiv.org/html/2509.25085v1) |
| jina-reranker-v2-base-multilingual / v3 | 278M / 0.6B | CC BY-NC 4.0 | Excluded (non-commercial) |
| Qwen3-Reranker-0.6B | 0.6B decoder | Apache 2.0 | Heavier than cross-encoders; KaLM paper puts its online compute at 42.4x vs 6.9x for a small alternative (https://arxiv.org/pdf/2606.22807) |
| mxbai-rerank (v2 base/large) | 0.5B / 1.5B | Apache 2.0 | English focus; test before use |
| mmarco-mMiniLMv2-L12-H384 | 118M | Apache 2.0 | Small, fast, weaker |

Latency evidence is contradictory. One report: 30 pairs with bge-reranker-v2-m3 in ~600-800 ms on CPU with a dynamic-batch ONNX export (hardware and pair length unspecified) (https://dev.to/gabrielanhaia/the-reranker-setup-that-actually-changes-recall5-1ole). Another: 5-7 CPU-seconds per candidate on 4 x86 cores with the community ONNX export (https://github.com/Dakera-AI/dakera-deploy/issues/295). First-principles estimate for the Ryzen 5 3600 [E]: 30 pairs x 300 tokens = 9,000 tokens x 0.6 GFLOP/token = 5.4 TFLOP, so **~10-30 s** (INT8 at the low end). 50 candidates: 18-50 s. That would double the RAG latency.

CPU-tier recommendation: rerank at most 10-15 candidates truncated to 256 tokens with INT8 bge-reranker-v2-m3 (est. 3-8 s), or skip the cross-encoder and rely on hybrid BM25 + dense with reciprocal rank fusion. Benchmark both against answer quality. On any GPU, rerank 50 candidates (well under 1 s).

## 5. Document parsing and OCR on CPU

| Tool | CPU speed | Turkish | License | Use |
|---|---|---|---|---|
| pypdfium2 / pdfplumber | Very fast text-layer extraction | Text layer is exact | Apache/BSD, MIT | Default for born-digital PDFs |
| PyMuPDF | Fastest text extraction | Exact | **AGPL-3.0 or commercial** | Avoid unless licensed |
| Docling | Median 0.79 s/page, mean 3.1 s/page on x86 CPU without OCR; EasyOCR adds ~13 s/page; 0.94 pages/s at 4 threads, 1.57 at 16 threads [M] (https://arxiv.org/html/2408.09869v4) | Depends on OCR engine plugged in (Tesseract, EasyOCR, RapidOCR) | MIT | **Default layout/table pipeline** |
| Marker 2 | 23.7 pages/s CPU in "fast, no OCR" mode; OCR modes benchmarked on a B200 GPU [M, vendor] (https://www.datalab.to/blog/marker-2, 2026-07-20) | Surya supports 90+ languages | **GPL-3.0 code; weights free only under $2M revenue/funding** (https://pypi.org/project/marker-pdf/) | Not shippable without a commercial license |
| Surya OCR | 1-3 s/page CPU [reported] (https://www.solosoft.dev/post/surya-ocr-2026/) | Good multilingual | Same restriction as Marker | Same |
| MinerU | Slowest in Datalab's comparison (0.54 pages/s on B200) | Uses PaddleOCR models | AGPL-3.0 | Avoid |
| Unstructured (OSS) | Wraps Tesseract/others; slow hi-res mode | Via Tesseract | Apache 2.0 | No advantage over Docling |
| Tesseract 5 (`tur`) | ~1-3 s/page/core at 300 dpi [E]; parallel across 6 cores = 2-6 pages/s aggregate is optimistic, 1-3 realistic | Mature `tur` traineddata incl. ç ğ ı İ ö ş ü | Apache 2.0 | **Default OCR on CPU** |
| PaddleOCR PP-OCRv5 / RapidOCR | Fast ONNX on CPU | Turkish listed in the Latin model, but maintainers said special characters (ç ğ ı ö ş ü) were not covered and were "planned for PaddleOCR 3.3" (https://github.com/PaddlePaddle/PaddleOCR/discussions/16482) | Apache 2.0 | Verify the current dictionary before use |
| docTR | Moderate | Default vocabularies lack ğ ş ı | Apache 2.0 | Needs fine-tuning |

Small VLM OCR:

- PaddleOCR-VL 1.6 (GGUF Q8_0, llama.cpp) took ~53 s/page on an Apple M5 Pro CPU [M] (https://codecut.ai/olmocr2-vs-paddleocr-vl/, 2026). On a Ryzen 5 3600 expect 1.5-3 min/page [E]: only viable as a fallback for a handful of hard pages (tables, stamps, handwriting).
- olmOCR-2, dots.ocr and similar 1-7B VLMs are GPU-tier tools: seconds per page on a 16 GB GPU.

Throughput for a 10,000-document corpus (assume 10 pages/doc, 30% scanned) [E]: 70,000 text-layer pages through Docling at ~1 page/s = ~20 h; 30,000 OCR pages through Tesseract at ~1-2 pages/s = 4-8 h. **Initial ingestion on the CPU tier is a multi-day batch job** (parse + OCR + embed) and must run resumably at night. On the GPU tier the same corpus is a few hours.

## 6. Hardware tiers and Turkish market prices

Prices are akakce.com listings as surfaced by search in September 2026; the DRAM market is volatile and GPU prices vary 1.5x between shops. Re-check at quote time.

| Component | Price (TRY) | Source |
|---|---|---|
| AMD Ryzen 5 3600 (tray) | ~4,277 | https://www.akakce.com/islemci/en-ucuz-amd-ryzen-5-3600-wof-alti-cekirdek-3-60-ghz-fiyati,376814455.html |
| AMD Ryzen 5 5600 (boxed) | ~6,104 | https://www.akakce.com/islemci/en-ucuz-amd-ryzen-5-5600-alti-cekirdek-3-50-ghz-kutulu-fiyati,2010103121.html |
| AMD Ryzen 5 7500F (AM5, DDR5) | ~6,899 | https://www.akakce.com/islemci/ryzen-5.html |
| DDR4 32 GB (2x16) 3200 CL16 | ~17,432 | https://www.akakce.com/ram/ddr4.html |
| DDR4 16 GB 3200 | ~7,160 | https://www.akakce.com/ram/ddr4.html |
| RTX 5060 Ti 16 GB | ~26,149 (PNY) to ~40,000 | https://www.akakce.com/ekran-karti/rtx-5060-ti.html |
| RTX 3090 24 GB | ~55,700 to ~70,600 (remaining new stock; used market cheaper) | https://www.akakce.com/ekran-karti/rtx-3090.html |
| RTX 4090 24 GB | ~81,000 to ~87,500 | https://www.akakce.com/ekran-karti/rtx-4090.html |
| RTX 5090 32 GB | from ~120,000 (akakce), average ~226,000 (hepsiburada) | https://www.akakce.com/ekran-karti/rtx-5090.html, https://www.hepsiburada.com/rtx-5090-ekran-karti-x-s52584 |

Note that 32 GB of DDR4 now costs about four times the Ryzen 5 3600 itself. Upgrading an existing 16 GB box to 32 GB (~17k TRY) is the single best-value step on the CPU tier because it unlocks MoE models.

### Tier 1: CPU only

- Hardware: Ryzen 5 3600 / 5600 class, 16 GB minimum, 32 GB recommended, NVMe SSD. A new AM4 build (5600 + B550 + 32 GB + 1 TB NVMe) is roughly 35-45k TRY [E].
- 16 GB: Qwen3.5-4B or Gemma 4 E4B, e5-base or EmbeddingGemma-300M, no cross-encoder or a 10-candidate rerank. 55-80 s per answer [E].
- 32 GB: Qwen3.5-35B-A3B (or Qwen3-30B-A3B), same answer time as the 4B with much better quality [E].
- Users: 5-10 named, 1-2 simultaneous. Initial indexing: days.

### Tier 2: entry GPU (RTX 5060 Ti 16 GB, ~26-40k TRY)

- 448 GB/s VRAM bandwidth. Qwen3.5-9B Q4 fully in VRAM: est. 50-70 tok/s generation, 1,500-3,000 tok/s prefill, answer in 5-8 s [E].
- Qwen3.5-35B-A3B does not fit 16 GB; run attention and shared layers on GPU and experts on CPU (`--n-cpu-moe`). The 5800X + 6 GB GTX 1660 Super measurement (pp 240, tg 15.7) is the floor; a 16 GB card holding more experts should reach est. 25-40 tok/s [E].
- Embeddings (bge-m3) and reranking (50 candidates) on GPU: indexing 50k chunks in minutes, rerank under 1 s.
- Users: 10-25 concurrent with llama-server `--parallel 4-8`.
- Even a cheap used 8 GB card is worth recommending: it moves prefill from ~60 to ~240+ tok/s, which is the dominant cost.

### Tier 3: RTX 3090/4090 (24 GB) or RTX 5090 (32 GB) / workstation

- 24 GB: Qwen3.5/3.6-35B-A3B Q4 fully in VRAM with moderate context; community reports 100+ tok/s on RTX 3090 class (https://huggingface.co/Qwen/Qwen3.6-35B-A3B/discussions/37). Answer in 3-5 s [E].
- 32 GB: Qwen3.6-27B dense or 35B-A3B with long context; VLM OCR (olmOCR-2 / PaddleOCR-VL) in-line during ingestion.
- Switch the LLM engine to vLLM for 25-50+ concurrent users (paged attention, continuous batching); keep llama.cpp images as the fallback.

## 7. WSL2 on Windows hosts

Many municipal and SMB servers are Windows. Findings:

- **Memory:** WSL2 takes up to 50% of host RAM by default and swap of 25% (https://oneuptime.com/blog/post/2026-02-08-how-to-configure-docker-desktop-memory-and-cpu-limits-on-windows/view). On a 16 GB host that leaves ~8 GB for the whole stack, which is not enough. Set `memory=12GB` (16 GB host) or `memory=26GB` (32 GB host) and `processors=12` in `%UserProfile%\.wslconfig`. A 16 GB Windows host is marginal; recommend 32 GB for Windows installs.
- **Memory reclaim vs mmap:** `autoMemoryReclaim=dropcache` releases page cache, and llama.cpp maps model files through the page cache, so the model can be evicted and re-read from disk. Use `gradual` (reclaims over 60-120 s, keeps hot cache, https://www.praveentechworld.com/blog/why-wsl2-vmmem-wont-free-ram-auto-memory-reclaim-fix) or run llama-server with `--mlock`/`--no-mmap`.
- **File system:** Windows drives under `/mnt/c` go through the 9P protocol and are slow for many small files (https://www.ceos3c.com/linux/wsl2-performance-optimization-speed-up-your-linux-experience/). Keep models, the database and the vector index inside the Linux ext4 VHDX. Enable `sparseVhd` so the VHDX shrinks after deletes. Document ingestion from a Windows share should copy files in, not index in place.
- **GPU:** CUDA in WSL2 works with only the Windows NVIDIA driver installed; never install a Linux display driver inside the distro (https://docs.nvidia.com/cuda/wsl-user-guide/). Containers need the NVIDIA Container Toolkit (native Docker) or Docker Desktop's WSL2 backend. AMD: ROCm on WSL covers a limited set of Radeon cards; Vulkan inside WSL is not practical. For AMD GPUs on Windows, a native Windows llama.cpp Vulkan build is the realistic path.
- **Docker Desktop vs Docker Engine in WSL:** Docker Desktop requires a paid subscription for organizations with more than 250 employees or more than USD 10M annual revenue (https://docs.docker.com/subscription/desktop-license/), which covers most municipalities and larger firms. Install Docker Engine (docker-ce, Apache 2.0) inside the WSL distro instead; it also avoids Desktop's extra VM overhead.
- **Service behaviour:** WSL does not start at boot and shuts the VM down when idle. Start it from a Windows scheduled task at boot and set `vmIdleTimeout` high. For LAN access use `networkingMode=mirrored` (Windows 11 22H2+); otherwise NAT needs `netsh portproxy` rules.

## 8. Recommendations

**Default runtime:** llama.cpp `llama-server` (MIT), pinned release, official CPU/CUDA/Vulkan/ROCm images. One instance for chat (`--parallel 2` on CPU, 4-8 on GPU, prompt cache on, thinking off), one for embeddings (`--embedding`), optional one for rerank (`--reranking`). vLLM is an opt-in engine for Tier 3 with >25 users. Keep the OpenAI-compatible API as the only contract so engines are swappable.

**Default models per tier:**

| Tier | LLM | Embedding | Rerank | Parsing / OCR |
|---|---|---|---|---|
| 1, 16 GB | Qwen3.5-4B Q4_K_M (Gemma 4 E4B as candidate) | multilingual-e5-base INT8 (EmbeddingGemma-300M as candidate) + BM25 hybrid | none or bge-reranker-v2-m3 INT8 on top 10 | pypdfium2 + Docling, Tesseract `tur` |
| 1, 32 GB | Qwen3.5-35B-A3B Q4_K_M (Gemma 4 26B-A4B as candidate) | same | same | same |
| 2, 16 GB GPU | Qwen3.5-9B on GPU, or 35B-A3B with experts on CPU | bge-m3 (dense + sparse) | bge-reranker-v2-m3, top 30-50 | Docling + Tesseract; VLM OCR fallback |
| 3, 24-32 GB GPU | Qwen3.5/3.6-35B-A3B fully on GPU (27B dense on 32 GB) | bge-m3 | bge-reranker-v2-m3 | Docling + PaddleOCR-VL/olmOCR-2 (license check) |

Exclude for commercial shipping: jina embeddings/rerankers (CC BY-NC), Marker/Surya (GPL + revenue cap), MinerU and PyMuPDF (AGPL).

**What we must benchmark ourselves (on a real Ryzen 5 3600, DDR4-3200, 16 and 32 GB):**

1. `llama-bench` pp512/pp2048/tg128 at 6 and 12 threads for Qwen3.5-4B, Qwen3.5-9B, Qwen3.5-35B-A3B, Qwen3-30B-A3B, Gemma 4 E4B, Gemma 4 26B-A4B (verifies the hybrid-attention CPU kernel risk). Mainline vs ik_llama.cpp once.
2. End-to-end RAG latency at 1,500 and 3,000 context tokens, 1, 2 and 4 parallel users; record time to first token and total.
3. A Turkish grounded-QA set (200+ questions from real municipal, legal and health documents, with answerable and unanswerable items) scored for correctness, citation faithfulness and abstention, modelled on arXiv 2609.28007. Include Trendyol-8B-T1 and Mergen-TR-Qwen3.5-9B as Turkish baselines.
4. Embedding recall@10 on the same corpus: e5-small/base/large, EmbeddingGemma-300M, bge-m3, turkish-e5-large, each with and without BM25 fusion; measured chunks/s on the 3600 with ONNX INT8 vs OpenVINO vs llama.cpp.
5. Reranker gain vs latency: none, top 10, top 30 with bge-reranker-v2-m3 INT8.
6. OCR character accuracy on Turkish scans (ç ğ ı İ ö ş ü specifically): Tesseract `tur`, current PP-OCRv5 Latin, EasyOCR; pages/min on 6 cores.
7. WSL2 on a 16 GB and 32 GB Windows host: same RAG latency test, plus behaviour after idle (model eviction) and after reboot.
