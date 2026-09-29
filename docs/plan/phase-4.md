# Phase 4: knowledge base and RAG

Status: in progress, started 2026-09-28. Steps 1 to 4 done ([knowledge-base.md](../design/knowledge-base.md)): in step 4 the page quality check ([page-quality.md](../benchmarks/page-quality.md)) and OCR, chosen by benchmark on the reference hardware and running in the worker ([ocr.md](../benchmarks/ocr.md)). Docling against the light parser is measured and decided ([parsing.md](../benchmarks/parsing.md)): the light parser stays, Docling is not adopted for v1. Step 5 is done (same design document). A first draft of the golden set for step 9 (225 questions, [eval/golden/](../../eval/golden/README.md)) is in place. The corpus is downloaded. Decisions it implements: [ADR 0003](../adr/0003-single-postgres-store.md), [0004](../adr/0004-job-queue.md), [0009](../adr/0009-model-runtime.md), [0010](../adr/0010-rag-pipeline.md). Scope: the knowledge base and search and chat sections of [v1-scope.md](../product/v1-scope.md).

The phase ends when a user can upload the evaluation corpus, ask questions in Turkish and get cited answers, and the evaluation harness reports the ADR 0010 metrics on it. Each step below ends with tests, a smoke run and its design document.

## Steps

| # | Step | Needs | Done when |
|---|---|---|---|
| 1 | **Blob store and upload.** `BlobStore` port with a local-volume adapter (content-addressed by SHA-256). Upload endpoint: size limit, type detected from the bytes, `write` permission on the collection, identical files linked. Document versions. | Nothing new | A file uploaded through the API is stored once, visible only to readers of its collection, and its version history is kept |
| 2 | **Job queue and worker role.** Procrastinate on the main database, the task wrapper (tenant context, actor, document lock), the `worker` process role, retries, and jobs enqueued in the upload transaction. Per-document status. | Step 1 | Upload enqueues a job in the same transaction; a worker picks it up; a rolled-back upload leaves no job; failed jobs are visible |
| 3 | **Text extraction for born-digital files.** `Parser` port. A light adapter first (PDF text layer, DOCX, XLSX, PPTX) so the pipeline runs end to end; per-page records with page numbers. | Step 2 | Born-digital documents reach `parsed` with page-accurate text |
| 4 | **Parser and OCR benchmark.** Docling (with and without its layout model) against the light adapter; Tesseract Turkish against alternatives; the per-page Turkish quality check. Results in `docs/benchmarks/`. | The evaluation corpus downloaded | A recorded decision on the default parser and OCR engine per tier |
| 5 | **Cleaning, chunking, entities, deduplication.** Structure-aware chunks (never across a table row), context prefixes, typed entities, duplicates linked. | Step 3 (step 4 for scanned files) | Chunk rules have property tests; entities extracted from the corpus are spot-checked |
| 6 | **Model runtime.** `ChatModel`, `Embedder`, `Reranker` ports; llama.cpp servers in the stack; embedding bake-off on the corpus. | Step 5, corpus | Embeddings stored as `halfvec` with HNSW; the chosen models are recorded with their benchmark |
| 7 | **Retrieval.** Exact identifier lookup, BM25 on lemmas and on raw tokens, dense vectors, weighted RRF, reranking, the permission filter in every candidate query. | Step 6 | A test proves fusion scores are never thresholded; permission tests show no candidate leaks |
| 8 | **Grounded answers and chat UI.** Refusal before generation, context assembly, structured output, number and identifier verification, citations to page and region, streaming, conversations, the document viewer. | Step 7 | The sources-first, answer-second flow works in the browser in Turkish and English |
| 9 | **Evaluation harness and golden set.** 150 to 300 Turkish questions over the corpus, CI gates from ADR 0010. | Steps 7 and 8, corpus | The harness runs in CI and reports every ADR 0010 metric |

## Open decisions

- ~~**Corpus download.**~~ Done 2026-09-28 ([eval/corpus/](../../eval/corpus/)).
- ~~**Where parsing runs.**~~ Settled 2026-09-29: no Docling in v1, so parsing stays in the worker image ([parsing.md](../benchmarks/parsing.md)); should a customer corpus need it later, it gets its own worker image.
