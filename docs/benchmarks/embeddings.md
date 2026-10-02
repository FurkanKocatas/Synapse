# Retrieval on the golden set: lexical, dense, fused, reranked

Status: **decided**, 2026-10-01: Furkan accepted [ADR 0018](../adr/0018-model-defaults.md). Phase 4, step 6 (the embedding bake-off) and the first measurements for step 7 (retrieval); the choice is at the end.

Method and scripts: [eval/retrieval/](../../eval/retrieval/README.md); questions: [eval/golden/](../../eval/golden/README.md), draft 1, 191 answerable questions, and their paraphrased copy.

## Method in one paragraph

The corpus is cut into chunks by the product's chunker from the light parser's blocks: 10,852 chunks from the pages that pass the quality check. A question is found at rank k when the top k chunks cover its evidence (its page, or a page where the same answer stands; a multi-document question needs a chunk from each document, so its Hit@1 is 0 by definition). Hit@1, Hit@10 and MRR@10, per question type. Two question sets: the golden set as written, whose questions share a third of their words with the evidence (they were written looking at the page), and a paraphrased copy that shares a tenth, reworded to avoid the source's words while keeping the document's name and every identifier. Real users are somewhere between the two. Everything runs on the reference machine's CPU (Ryzen 5 6600H, 6 threads).

## Document context in every chunk

A chunk cut from the middle of a document does not say which document it is: which municipality, which law, which year; the questions do. Putting a document context in front of every chunk (ADR 0010, ingestion rule 9) is measured first, with BM25 on five-letter prefixes (below), on the golden set as written:

| Chunk text | Hit@1 | Hit@10 | MRR@10 |
|---|---|---|---|
| heading path and text (what ingestion indexes today) | 0.57 | 0.87 | 0.666 |
| the published file name in front | 0.62 | 0.92 | 0.717 |
| the document's first 30 words in front | 0.65 | 0.94 | 0.749 |
| **both** | **0.66** | **0.96** | **0.764** |
| the corpus's hand-written title in front (an upper bound: no upload has it) | 0.69 | 0.95 | 0.774 |

Only what ingestion knows is used: the file name a document was published under (the name it would be uploaded with, from "63 insan kay ve egt md mevzuat degisikligi nedeniyle memur kadro ..." to as poor as "Hukuk Komisyonu ca5255ad79") and the opening words, taken from the first chunks together (usually the issuing body, the document type and its number). Together they come within a point of the hand-written titles. Every number below uses them.

## Lexical search

| Run | as written: Hit@1 / Hit@10, MRR | paraphrased: Hit@1 / Hit@10, MRR |
|---|---|---|
| BM25 on words | 0.64 / 0.95, 0.744 | 0.29 / 0.57, 0.375 |
| BM25 on five-letter prefixes | 0.66 / 0.96, 0.765 | 0.28 / 0.62, 0.379 |
| BM25 on Snowball Turkish stems | 0.64 / 0.96, 0.756 | |

Words are lower-cased the Turkish way; identifiers ("2026/16", "E-81912396-105.04") are also indexed whole. Five-letter prefixes (four and six are within a point) stand in for Turkish lemmas; the Snowball Turkish stemmer, which PostgreSQL's `turkish` text search configuration uses, is as good within two questions, so search can use PostgreSQL's own configuration on text lower-cased by `turkish.lower` first. Checked on the product's database (PostgreSQL 18, `en_US.utf8`): `to_tsvector('turkish', ...)` gives "belediye", "karar", "müdürlük", "ödenek", "istanbul" for "Belediyelerin", "kararları", "müdürlüğünün", "ödeneği", "İSTANBUL"; but PostgreSQL's `lower('IĞDIR')` is "iğdir", not "ığdır", so the text must reach it lower-cased already. On questions as written, lexical search alone reaches Hit@10 0.96; **on paraphrased questions it falls to 0.62**: it finds what shares the source's words and little else.

## Exact identifier lookup

ADR 0010 (query rule 2) looks up the identifiers of a question exactly. Measured as a run of its own: the question's typed entities (dates, decision, law and article numbers, amounts, parcels; [entities.py](../../backend/src/synapse/knowledge/entities.py)) looked up in the chunks' entities, chunks holding more of them first. It makes ranking worse (identifier questions Hit@1 0.71 to 0.60, Hit@10 1.00 to 0.89), and so did every variant tried (only identifiers held by at most 5, 20 or 100 chunks; fused by rank instead of put first; boosting whole documents instead of chunks, which was neutral). Only 25 of the 62 identifier questions contain an identifier (the rest ask for one: "hangi maddede düzenlenir?"), and the chunk that holds a question's identifier (a decision's header, an amendment note: "5393 sayılı" is cited in hundreds of chunks) is rarely the one that answers. BM25 already finds the right chunk from the identifier's tokens: all 43 questions that contain an identifier have their answer in its top 10, only 0.63 at rank 1, so they need a better order among the candidates, not more candidates. The lookup stays for a question that is only an identifier ("2026/16 sayılı karar"), which the golden set does not have yet.

**As a tie-breaker after reranking** (2026-10-02, [eval/retrieval/identifiers.py](../../eval/retrieval/identifiers.py)): the product's reranked first 15 (the `synapse-golden` stack, both question sets) saved once, then reordered so that the chunks holding more of the question's identifiers (its tokens with a digit and its typed entities, in the chunk's title, headings or text) come first: among all 15, or only among those the reranker scored within 3, 2 or 1 of its best; with years or without; anywhere in the text or as whole tokens. Identifier Hit@1, as written and paraphrased:

| order | as written | paraphrased | all types, as written |
|---|---|---|---|
| the reranker's | **0.806** | **0.629** | **0.754** |
| identifiers first | 0.710 | 0.532 | 0.670 |
| identifiers first, years left out | 0.710 | 0.532 | 0.681 |
| the same within 3 of the best | 0.790 | 0.581 | 0.743 |
| within 1 | 0.806 | 0.597 | 0.749 |

No variant lifts it, and the reason is in the misses: in every one of the 12 identifier questions (as written) whose evidence is not first, the first chunk is the right document's, another page of it, and the question's identifiers (the decision's own number, the law's) stand on every page of that document, or the question has none the extraction reads ("70 sayılı" is too short). The right document comes first for all 62; what is left is the page within it, which identifiers cannot tell. Not adopted. One miss is retrieval's alone: for g5-20 (an article of the Turkish Code of Obligations) the evidence page is not in the first 15 at all, and the answer took a wrong law number from another article.

## Embedding candidates and their cost

Every candidate is multilingual, allowed by ADR 0016 without review (MIT or Apache-2.0) and needs no remote code. Each embeds with the prefixes its model card prescribes, 512 tokens at most. Speed on a fixed sample of 256 chunks (341 tokens on average), 6 threads, nothing else running:

| Model | Parameters | PyTorch fp32 | ONNX Runtime fp32 | ONNX Runtime int8 | One question, int8 |
|---|---|---|---|---|---|
| multilingual-e5-small | 118M | 10.6 chunks/s | 12.2 | 13.5 | 6 ms |
| multilingual-e5-base | 278M | 4.3 | 4.6 | 7.6 | 11 ms |
| granite-embedding-278m-multilingual | 278M | 0.8 | 4.5 | 7.2 | 12 ms |
| bge-m3 | 568M | 1.4 | 1.3 (whole corpus) | not usable (below) | 65 ms (fp32) |

bge-m3 on llama.cpp is faster still, on the CPU and far more on the integrated GPU; see [llama.cpp](#llamacpp-on-the-cpu-and-on-the-integrated-gpu) below.

ONNX Runtime runs each model's published graph with its own pooling ([onnx_encoder.py](../../eval/retrieval/onnx_encoder.py), what the product's ONNX Runtime adapter would do, ADR 0009); int8 quantises the weights once, dynamically (the recipe optimum calls "avx2"). The full-precision ONNX vectors equal PyTorch's (cosine 1.000), the int8 ones stay at 0.996. int8 is 1.6 to 1.7 times ONNX full precision on the base models; granite under PyTorch is five times slower than the same-sized e5-base, on ONNX they are equal. At 7.6 chunks per second a customer's 100,000 chunks take under four hours, the resumable overnight load ADR 0010 expects; bge-m3 at 1.4 would take twenty.

**int8 is not usable here for base-sized models.** The recipe optimum calls "avx2" overflows on a CPU with AVX2 but no VNNI, the reference machine's: e5-base's vectors came out at cosine 0.90 of full precision, granite's at 0.84, and they ranked like much worse models. With the range reduced to 7 bits they stay at 0.97 to 0.98, which still costs e5-base 13 points of Hit@1 alone (0.57 to 0.44; paraphrased 0.41 to 0.30), 2 to 5 fused with BM25. e5-small keeps cosine 0.996 and loses 5 points alone, nothing fused. So the CPU tier runs full precision on ONNX Runtime: its vectors equal PyTorch's, and it is as fast or faster (granite five times).

## Dense and fused retrieval

Over the whole corpus, full precision (ONNX Runtime), Hit@1 / Hit@10 and MRR@10:

| Run | as written | paraphrased |
|---|---|---|
| BM25 on prefixes | 0.66 / 0.96, 0.765 | 0.28 / 0.62, 0.379 |
| e5-small | 0.54 / 0.85, 0.640 | 0.32 / 0.69, 0.434 |
| e5-base | 0.57 / 0.84, 0.658 | 0.41 / 0.76, 0.506 |
| granite-278m | 0.36 / 0.71, 0.459 | 0.19 / 0.54, 0.296 |
| **bge-m3** | 0.64 / 0.90, 0.726 | **0.48 / 0.86, 0.605** |
| BM25 + e5-small, reciprocal rank fusion | 0.63 / 0.92, 0.729 | 0.37 / 0.72, 0.465 |
| BM25 + e5-base, reciprocal rank fusion | 0.63 / 0.91, 0.724 | 0.36 / 0.76, 0.475 |
| the same, BM25's ranks weighted twice | 0.65 / 0.94, 0.741 | 0.35 / 0.72, 0.463 |
| BM25 + bge-m3, reciprocal rank fusion | **0.68 / 0.94, 0.772** | 0.37 / 0.81, 0.500 |

On questions worded like the source, lexical search is best and fusion with bge-m3 edges past it; on paraphrased ones dense retrieval is best and BM25 drags fusion down. **bge-m3 is the best encoder by a wide margin** (paraphrased Hit@10 0.86 against e5-base's 0.76 and e5-small's 0.69), at 3.4 times e5-base's cost: the corpus took 2.3 hours, 100,000 chunks would take about 21 on the reference machine. granite is the weakest, even in full precision.

## Reranking

bge-reranker-v2-m3 (Apache-2.0, 568M, multilingual) reads each question with each of its first stage's top 10 chunks and reorders them (ADR 0010, query rule 5):

| Candidates, then reranked | as written | paraphrased |
|---|---|---|
| BM25 on prefixes | 0.66 / 0.96, 0.765 | 0.28 / 0.62, 0.379 |
| BM25, reranked | **0.77** / 0.96, **0.852** | 0.42 / 0.62, 0.495 |
| BM25 + e5-base fused, reranked | 0.73 / 0.91, 0.810 | 0.52 / 0.76, 0.609 |
| bge-m3 | 0.64 / 0.90, 0.726 | 0.48 / 0.86, 0.605 |
| bge-m3, reranked | 0.74 / 0.90, 0.805 | **0.59 / 0.86, 0.696** |
| BM25 + bge-m3 fused | 0.68 / 0.94, 0.772 | 0.37 / 0.81, 0.500 |
| BM25 + bge-m3 fused, reranked | 0.75 / 0.94, 0.835 | 0.55 / 0.81, 0.641 |
| bge-m3, top 20 reranked | 0.75 / 0.93, 0.822 | 0.60 / 0.88, 0.707 |
| **BM25 + bge-m3 fused, top 15 reranked** | **0.76 / 0.97, 0.853** | **0.60 / 0.86, 0.697** |
| BM25 + bge-m3 fused, top 20 reranked | 0.76 / 0.97, 0.853 | 0.59 / 0.88, 0.704 |

Reranking adds 7 to 18 points of Hit@1 on every first stage and both sets, and reaches the Hit@1 target on questions as written (identifier questions 0.71 to 0.82, tables 0.74 to 0.91). It cannot add what its candidates lack: Hit@10 stays the first stage's, so the first stage sets the ceiling. Which first stage is best depends on the wording: BM25 on questions worded like the source, bge-m3 on paraphrased ones (their Hit@1 0.42 against 0.59), their fusion in between on both (0.75 and 0.55). Reranking BM25's top 15 instead of 10 changes Hit@1 by a point. **The fusion's top 15, reranked, is as good as the best of either on both sets**: BM25's result on questions as written (0.76 / 0.97, 0.853) and bge-m3's on paraphrased ones (0.60 / 0.86, 0.697); 20 candidates add nothing more. (The runs with 15 and 20 candidates are on the integrated GPU, below; for the paraphrased ones whitespace was collapsed before llama.cpp tokenized, as for every later run.)

Cutting question and chunk to fewer tokens is no way out. At 384 tokens (5.9 s) Hit@1 falls a point, at 256 (3.8 s) twenty (0.77 to 0.57, MRR 0.852 to 0.700): a chunk begins with its document context and heading path, and the answer is often past its first 256 tokens.

**Its cost on the CPU is the problem.** Ten candidates take 8.2 s per question under PyTorch on the 6600H, 10.6 s on ONNX Runtime in full precision (a graph exported from the PyTorch weights; it ranks the same) and 6.6 s with int8 weights (whose quality, after the encoders, is not to be trusted without a run of its own). The budget for sources on screen is 3 seconds (ADR 0009). On the integrated GPU it fits (below).

## llama.cpp on the CPU and on the integrated GPU

llama.cpp, ADR 0009's default engine for chat, also serves encoders (`--embedding`, `--reranking`), on the CPU or on a GPU through Vulkan, which current integrated GPUs support. The reference machine has one: the 6600H's Radeon 680M (12 compute units, no memory of its own: 3 GB of the system memory are reserved for it, and it may use up to 9 GB). bge-m3 and the reranker were converted from the same revisions with llama.cpp's own converter, at the pinned server image's build (b11243), to 16-bit and to 8-bit (Q8_0) weights; the script tokenizes and cuts texts exactly as on the other backends ([llama_encoder.py](../../eval/retrieval/llama_encoder.py)).

| bge-m3 | chunks/s | one question | reranker, 10 candidates: median (90th percentile) |
|---|---|---|---|
| PyTorch fp32, CPU | 1.4 | | 8.2 s |
| ONNX Runtime fp32, CPU | 1.3 | 65 ms | 10.6 s |
| llama.cpp 16-bit, CPU | 2.2 | 58 ms | 5.3 s (5.8) |
| llama.cpp Q8_0, CPU | 1.8 | 65 ms | 6.8 s (7.6) |
| llama.cpp 16-bit, integrated GPU | 3.5 | 61 ms | 3.3 s (3.8), all questions |
| **llama.cpp Q8_0, integrated GPU** | **4.4** (whole corpus: 41 minutes) | 48 ms | **2.5 s (2.9)**, all questions |

The quality is the same. The integrated GPU's 16-bit vectors are at cosine 0.9997 of ONNX Runtime's (lowest 0.9989, 32 chunks); with Q8_0 weights over the whole corpus bge-m3 ranks as on ONNX Runtime (as written 0.64 / 0.90, MRR 0.729 against 0.726; paraphrased 0.48 / 0.87, 0.607 against 0.605). The reranker orders candidates as PyTorch does: with Q8_0 its result over all questions is PyTorch's to the third decimal (0.77 / 0.96, 0.852), with 16 bits 0.76 / 0.96, 0.849. Unlike ONNX Runtime's int8 on this CPU, 8-bit weights cost nothing on the GPU; on the CPU llama.cpp's 8-bit is slower than its 16-bit, so there it is not used.

One setting matters: llama.cpp computes attention over all the texts of a physical batch at once, masked, so large batches waste work (bge-m3 at 8,192 tokens per batch: 1.6 chunks per second; at 512, one or two chunks per batch: 4.5). Flash attention recovers most of the loss at large batches and costs a little at 512. The servers run with batches of 512 tokens, 16 slots for embedding and 10 for reranking; bge-m3's server holds about 1.2 GB of shared memory.

On the reference machine the integrated GPU makes bge-m3 affordable (100,000 chunks in about 6.3 hours, one night), brings the reranker within the 3-second budget and leaves the CPU to parsing and OCR. A machine without a usable GPU still gains from llama.cpp: 1.7 times ONNX Runtime's speed on bge-m3, 1.6 times PyTorch's on the reranker.

## Choice

- **First stage: BM25 and bge-m3, fused by reciprocal rank; their top 15 to the reranker.** BM25 on five-letter prefixes or PostgreSQL's `turkish` stems (equal here), identifiers indexed whole, the document context in front of every chunk; bge-m3's dense vectors. On questions worded like the source it keeps BM25's result, on paraphrased ones bge-m3's; BM25 alone loses 18 points of Hit@1 on paraphrased questions, bge-m3 alone 4 to 7 points of Hit@10 on questions as written.
- **Reranker: bge-reranker-v2-m3.** 15 candidates take 3.8 s on the reference machine's integrated GPU (Q8_0; 90th percentile 4.3), 10 take 2.5 s at 1 point of Hit@1 on questions as written and 5 on paraphrased ones. Either way the fused order is on screen within a second and the reranked order replaces it when it arrives, so the 3-second budget holds for sources; on the CPU alone (about 5 s for 10) the same.
- **Encoders on llama.cpp:** Q8_0 on a GPU through Vulkan, 16-bit on the CPU alone; batches of 512 tokens.
- **Not chosen:** e5-base (10 points lower paraphrased Hit@10), ONNX Runtime (slower, int8 unusable on this CPU), inputs cut to fewer tokens.

The model choice as a whole, with the chat model ([answers.md](answers.md)), is [ADR 0018](../adr/0018-model-defaults.md), accepted.

## Next steps

1. ~~**The same numbers from the product's search**~~ Done (step 7, [search.md](../design/search.md#measured)): through the product's API on its own ingestion, reranked, 0.75 / 0.97 (MRR 0.843) as written and 0.56 / 0.83 (0.656) paraphrased, with five-letter terms in PostgreSQL's BM25, which beat its Snowball stems there too. CI is to fail if they fall more than a point below these.
2. **Identifier questions.** Hit@1 0.82 against ADR 0010's target of 0.98 for them. The exact lookup made ranking worse as a first stage; measure it as a tie-breaker after reranking, among candidates the reranker scores close.
3. **Multi-document questions** need a chunk from each document in the top 10 (0.71 to 0.86 today): measure keeping at least one chunk per document among the reranked candidates.
4. **Another integrated GPU** (an Intel one, the other common kind in office machines) before the installer relies on Vulkan everywhere: speed and the same rankings.
5. The golden set's review by a person (ADR 0010), and questions that are only an identifier ("2026/16 sayılı karar"), which it does not have yet.
