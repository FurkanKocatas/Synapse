# 0009. Model runtime: llama.cpp behind provider ports

- Status: accepted
- Date: 2026-09-28

## Context

The same product must run on a CPU-only box, on consumer GPUs from any vendor, and optionally against external APIs. On CPU, prompt processing dominates latency. External APIs with personal data in the prompt are a transfer abroad under KVKK and need a standard contract, so they must be deliberate. Typical risks in LLM platforms: a model gateway reachable directly by users (bypassing guardrails and model restrictions), clients able to append to the system prompt, and tool failures that go unnoticed.

Research: [02-hardware-inference.md](../research/02-hardware-inference.md), [01-market.md, section 3.1](../research/01-market.md).

## Decision

**Ports.** The application talks to models only through three Python protocols: `ChatModel`, `Embedder`, `Reranker`. Adapters implement them. No other code imports an HTTP client for model calls.

**Default engine.** llama.cpp `llama-server` (MIT), a pinned release, official images per backend (CPU, CUDA, Vulkan, ROCm):

- One instance for chat (`--parallel 2` on CPU, 4 to 8 on GPU; prompt cache on; thinking mode off by default).
- One instance for embeddings (`--embedding`) and one for reranking (`--reranking`), or an ONNX Runtime adapter for encoders if benchmarks show it is faster on CPU.
- Each instance has its own API key and listens only on the internal Docker network.

**Optional engines.** vLLM adapter for large GPU installs; OpenAI-compatible adapter for external providers.

**External providers are opt-in per tenant**, off by default, configured by an admin, and:

- every call is audited (provider, model, tenant, user, token counts, not content);
- personal data is masked before sending (national ID, phone, email, IBAN, names from a tenant list), with the mapping kept locally to restore the answer;
- a collection can be marked "never send externally".

**Model selection is server-side.** Users choose among models the admin enabled; the server validates the choice. The system prompt is assembled only on the server from versioned templates; clients cannot add to it. No model endpoint is reachable from the browser.

**Defaults per tier** (final choice after the Turkish grounded-QA benchmark):

| Tier | Chat | Embedding | Rerank |
|---|---|---|---|
| CPU, 16 GB | 4B class (Qwen3.5-4B or Gemma 4 E4B), Q4_K_M | Chosen by bake-off, favouring indexing speed | Top 10 to 15 or none |
| CPU, 32 GB | 30 to 35B MoE (about 3B active), Q4_K_M | Same | Same |
| GPU 16 GB | 9B dense on GPU, or MoE with experts on CPU | Bake-off winner, quality first | Top 30 to 50 |
| GPU 24 GB and up | 35B MoE fully on GPU | Same | Same |

**Latency budget.** Sources on screen within 3 seconds; first answer token within 60 seconds and full answer within 2 minutes on the 16 GB CPU tier at the default context size. Anything slower is a bug.

**Health.** A model call that fails or times out returns a typed error that the UI shows; it is never swallowed. Tool calls are validated against their schema before execution, and a failing tool raises an alert.

## Consequences

- One model format (GGUF) and one API style to support across all tiers.
- Engine choice is a configuration value; swapping engines does not touch business code.
- We must benchmark candidate models on real hardware before fixing defaults (see [0010](0010-rag-pipeline.md)).

## Alternatives considered

- **Ollama:** convenient, but lags upstream on new architectures and brings its own model manager.
- **vLLM everywhere:** its CPU backend targets AVX-512 servers; fine on GPUs only.
- **OpenVINO Model Server:** credible for encoders on x86; kept as a benchmark candidate for the `Embedder` and `Reranker` ports.
