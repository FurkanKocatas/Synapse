# 0010. RAG pipeline v1 and its quality gates

- Status: accepted
- Date: 2026-09-28

## Context

Retrieval and answer quality is the product's first priority. Typical RAG systems lose quality in predictable places: tables split mid-row, thresholds applied to fusion scores that carry no absolute meaning, identifiers confused with dates or other numbers, page numbers lost before citations, and invented facts when retrieval returns nothing. On CPU, every token of context costs prefill time, so precision is also the latency lever.

Research: [03-rag.md](../research/03-rag.md), [02-hardware-inference.md](../research/02-hardware-inference.md), [00-summary.md, section 5](../research/00-summary.md).

## Decision

**Ingestion**

1. Detect file type from content, not extension. Identical files (SHA-256) are linked, not re-processed.
2. Parse with Docling behind a `Parser` port, routed by type: born-digital PDF (text layer), scanned or broken PDF and images (OCR), DOCX/PPTX (native), XLSX/CSV (typed tables), email (headers, body, attachments as child documents).
3. **Per-page quality check on every page:** Turkish character profile, dotted and dotless i ratio, lexicon hit rate, markup artifacts, near-empty pages. Failing pages are re-OCR'd; the score is stored and low-quality pages are shown to admins.
4. OCR behind an `OCR` port. Default Tesseract with Turkish data; other engines only after they pass the Turkish character benchmark.
5. Clean: remove repeated headers and footers, hidden text, math artifacts; attach signature blocks as metadata; NFC normalization and Turkish-aware casing (never plain `lower()`).
6. Extract typed entities (decision and regulation numbers, dates, amounts, parcels, article numbers) with configurable per-tenant rules into `chunk_entities`.
7. Chunk by structure: about 350 tokens, max 512, never across level 1 or 2 headings, **never inside a table row**. Large tables split by row groups with repeated headers, plus a table summary chunk, plus a typed copy for calculation.
8. Deduplicate: exact hash, MinHash (document level), SimHash (chunk level); duplicates become links.
9. Deterministic context prefix (title, type, date, number, heading path, page) on every chunk; an LLM document summary is added in the background later.
10. Commit everything in one transaction ([0003](0003-single-postgres-store.md)).

**Query**

1. Condense follow-ups into a standalone query only when there is history. Rule-based normalization and tenant synonyms always.
2. Parse identifiers in the query; typed exact lookup.
3. Candidate lists, each with the permission filter in SQL ([0007](0007-authorization.md)): exact identifier, BM25 on lemmas, BM25 on raw tokens, dense vectors.
4. Weighted reciprocal rank fusion. **Fusion scores are never thresholded**; a test enforces this.
5. Rerank the top candidates (count per tier). **Thresholds apply only to calibrated reranker scores**, set per model from the golden set.
6. **Refuse before generating** if the best calibrated score is below the answerability threshold: reply "not found in your documents" with possibly related documents, and do not call the LLM.
7. Final context: at most 6 chunks, at most 3 per document, diversity by MMR, top 3 expanded to their parent section, hard token cap per tier.
8. Aggregation questions over tables go to a read-only SQL tool on typed tables the user may access. The model never adds numbers itself.
9. Generate with a structured output (`answer`, `citations`, `sufficient`). Source text is wrapped as data; instructions found inside documents are ignored.
10. Verify: every number and identifier in the answer must appear in the cited sources or in tool output; otherwise regenerate once, then strip the claim or refuse. Every citation resolves to document, page and region.

**Evaluation gates**

- A golden set per corpus: 150 to 300 questions (factual, identifier, table, multi-document, 15% unanswerable), labels anchored to document, page and content hash.
- CI fails if retrieval metrics drop by more than 1 point, if any unsupported number appears, or if refusal on unanswerable questions drops.
- v1 targets: Hit@10 at least 95%, Hit@1 at least 75%, identifier Hit@1 at least 98%, refusal on unanswerable at least 90% with false refusal at most 5%, page resolution 100%.
- Every query logs per-stage candidate counts and scores; an alert fires if post-threshold counts are zero while pre-threshold counts are not, above a set rate.

**Decided by benchmark, not by this ADR:** embedding model, reranker candidate count, chat model per tier, OCR engine. Each benchmark result is recorded in `docs/benchmarks/`.

## Consequences

- Ingestion is heavier and slower than naive chunking; on CPU the first full corpus load is a resumable overnight job.
- The golden set is a product artifact, built with each customer during onboarding.

## Alternatives considered

- **HyDE and multi-query rewriting:** too slow on CPU and harmful for identifier queries; revisit behind a "deep search" mode.
- **LLM-written context for every chunk:** hundreds of CPU hours per corpus; replaced by deterministic prefixes plus one summary per document.
- **GraphRAG and LightRAG:** indexing cost unaffordable on CPU. Late-interaction retrieval (Turkish ColBERT models) is the leading candidate for v1.x.
