# Grounded answers in Turkish: the chat model bake-off

Status: **decided**, 2026-10-01: Qwen3.5-4B is the chat model of the 16 GB tier ([ADR 0018](../adr/0018-model-defaults.md), accepted by Furkan). The Turkish grounded-QA benchmark that [ADR 0009](../adr/0009-model-runtime.md) makes the choice depend on, and the first measurement for phase 4, step 8.

Method and script: [eval/answers/](../../eval/answers/README.md); questions: [eval/golden/](../../eval/golden/README.md), the same 75 drawn with a fixed seed for every run: 66 answerable (19 factual, 24 identifier, 15 table, 8 multi-document) and 9 unanswerable.

## Method in one paragraph

Each question gets six chunks as numbered sources, from two contexts: `oracle`, its evidence chunks among BM25's other top chunks, shuffled (what the model makes of good sources), and `retrieved`, the top six of BM25 reranked by bge-reranker-v2-m3 (what it makes of what search finds today; [embeddings.md](embeddings.md)). The model answers as JSON (`answer`, `citations`, `sufficient`) under a grammar the server enforces, told to use the sources only and to say "Belgelerde bulunamadı." otherwise. The prompt is about 2,800 tokens. Both candidates are Apache-2.0 and 4B-class: Qwen3.5-4B (Q4_K_M, 2.7 GB) and Gemma 4 E4B (Q4_0, 4.6 GB), on llama.cpp (build b11243), on the reference machine's integrated GPU through Vulkan, and on its CPU alone for timings.

**Scoring by hand.** The script counts an answer correct when it contains the golden answer after Turkish lower-casing. That misses correct answers written otherwise: "3 yıl" for "üç yıl", "302.250.000 TL" for "302250000", "920.000 Türk Lirası" for "dokuz yüz yirmi bin Türk lirası", "22.12.2023 tarih ve 2023/1497" for "22.12.2023 tarih 2023/1497". Every answer the script scored wrong was read against the golden answer and its evidence; the ones that state the golden answer count as correct below (Qwen 11 and 14 of them, Gemma 3 and 2: Qwen answers short, and short answers miss the golden wording more often). The script now reads numbers as numbers ([numerals.py](../../eval/answers/numerals.py): digits, thousands separators, Turkish number words), which closes 5 and 6 of Qwen's gaps and none the wrong way; what is left is wording ("üyeden" for "kişiden", "tarih ve" for "tarih"). An answer that changes an identifier ("E91810702" for "E-91810702") stays wrong. Three questions both models got wrong the same way were checked against the corpus: the golden answers stand (a 2026 amendment of HMK over the older text; a table row read as a sum of three others; an attorney fee tariff taken for the consumer arbitration limit).

## Results

Correct answers to answerable questions, refusals of unanswerable ones, answerable questions refused (false refusals) and broken outputs:

| | Qwen3.5-4B, oracle | Qwen3.5-4B, retrieved | Gemma 4 E4B, oracle | Gemma 4 E4B, retrieved |
|---|---|---|---|---|
| **correct, by hand** | **57/66 (0.86)** | **56/66 (0.85)** | 47/66 (0.71) | 51/66 (0.77) |
| correct, by the script | 51/66 (0.77) | 48/66 (0.73) | 44/66 (0.67) | 49/66 (0.74) |
| factual | 17/19 | 17/19 | 15/19 | 16/19 |
| identifier | 23/24 | 21/24 | 14/24 | 17/24 |
| table | 13/15 | 14/15 | 12/15 | 13/15 |
| multi-document | 4/8 | 4/8 | 6/8 | 5/8 |
| unanswerable refused | 8/9 | 8/9 | 8/9 | 7/9 |
| false refusals | 5 | 4 | 11 | 9 |
| broken outputs (400 tokens, no JSON) | 0 | 0 | 3 | 2 |
| a correct answer cites its evidence | 53/57 | 51/56 | 36/47 | 48/51 |

**Qwen3.5-4B is better by 8 to 15 points**, most on identifiers (23 of 24 against 14), refuses answerable questions half as often and never breaks its output. Gemma 4 E4B is better on multi-document questions, where Qwen answers one document and misses the other. Qwen's quality holds from oracle sources to retrieved ones (0.86 to 0.85): search as it is today does not cost answers. Both miss the same kinds of question: a number in a wide table read from the wrong column, two identifiers side by side ("KKU07.02" for "KKU07.01"), and the unanswerable question on the consumer arbitration limit, answered with an amount from another tariff; answer verification (ADR 0010, query rule 10) is what should catch the last two.

Gemma's broken outputs are the grammar: with a JSON schema, Gemma 4 thinks in plain text first whatever `enable_thinking` says, and runs out of tokens. Thinking off on the server (`--reasoning-budget 0`) fixed it for all but those 5 of 150; without it, 7 of 10.

## Speed

Medians over the 150 answers of each model on the integrated GPU, and over 10 oracle answers on the CPU alone (6 threads):

| | prompt, about 2,800 tokens | generation | whole answer (90th percentile) |
|---|---|---|---|
| Qwen3.5-4B, integrated GPU | 16.6 s (171 tokens/s) | 21.3 tokens/s | 20.2 s (25.8) |
| Gemma 4 E4B, integrated GPU | 12.6 s (216 tokens/s) | 19.3 tokens/s | 16.7 s (23.8) |
| Qwen3.5-4B, CPU | 43.7 s (62 tokens/s) | 10.8 tokens/s | 48.6 s (longest 61.0) |
| Gemma 4 E4B, CPU | 46.4 s (56 tokens/s) | 10.1 tokens/s | 54.2 s (longest 78.3) |

Both meet the latency budget of the 16 GB tier (first token within 60 seconds, the whole answer within 2 minutes) on the CPU alone, and the integrated GPU cuts the time to the first token by 2.6 to 3.7 times. The chat server's memory on the CPU: Qwen 4.2 GB, Gemma 6.6 GB.

## Limits

- 75 questions: one answerable question is 1.5 points; the gap between the models is five to ten times that, the gap between contexts is not.
- Hand scoring is one reader's; the ids re-scored are listed in [eval/answers/README.md](../../eval/answers/README.md).
- The retrieved context is BM25 reranked; the first stage that will ship ([embeddings.md](embeddings.md#choice)) finds more on paraphrased questions, which this run does not use.
- Answers are not yet verified against their sources (ADR 0010, query rule 10), and refusal before generation (rule 6) is not in the loop: both would change refusals and false refusals.

## Next steps

1. A scorer that also accepts a golden answer's wording varied (a judge that compares the answer's facts, not its words), so the script agrees with the hand scoring; numbers are done.
2. The same bake-off on the paraphrased questions with the shipping first stage.
3. Answer verification (ADR 0010, query rule 10) measured on these outputs: how many of the wrong numbers it catches.
