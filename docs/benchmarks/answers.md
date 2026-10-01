# Grounded answers in Turkish: the chat model bake-off

Status: **decided**, 2026-10-01: Qwen3.5-4B is the chat model of the 16 GB tier ([ADR 0018](../adr/0018-model-defaults.md), accepted by Furkan). The Turkish grounded-QA benchmark that [ADR 0009](../adr/0009-model-runtime.md) makes the choice depend on, and the first measurement for phase 4, step 8.

Method and script: [eval/answers/](../../eval/answers/README.md); questions: [eval/golden/](../../eval/golden/README.md), the same 75 drawn with a fixed seed for every run: 66 answerable (19 factual, 24 identifier, 15 table, 8 multi-document) and 9 unanswerable.

## Method in one paragraph

Each question gets six chunks as numbered sources, from two contexts: `oracle`, its evidence chunks among BM25's other top chunks, shuffled (what the model makes of good sources), and `retrieved`, the top six of BM25 reranked by bge-reranker-v2-m3 (what it makes of what search finds today; [embeddings.md](embeddings.md)). The model answers as JSON (`answer`, `citations`, `sufficient`) under a grammar the server enforces, told to use the sources only and to say "Belgelerde bulunamadı." otherwise. The prompt is about 2,800 tokens. Both candidates are Apache-2.0 and 4B-class: Qwen3.5-4B (Q4_K_M, 2.7 GB) and Gemma 4 E4B (Q4_0, 4.6 GB), on llama.cpp (build b11243), on the reference machine's integrated GPU through Vulkan, and on its CPU alone for timings.

**Scoring by hand.** The script counts an answer correct when it contains the golden answer after Turkish lower-casing. That misses correct answers written otherwise: "3 yıl" for "üç yıl", "302.250.000 TL" for "302250000", "920.000 Türk Lirası" for "dokuz yüz yirmi bin Türk lirası", "22.12.2023 tarih ve 2023/1497" for "22.12.2023 tarih 2023/1497". Every answer the script scored wrong was read against the golden answer and its evidence; the ones that state the golden answer count as correct below (Qwen 11 and 14 of them, Gemma 3 and 2: Qwen answers short, and short answers miss the golden wording more often). The script now reads numbers as numbers ([numerals.py](../../backend/src/synapse/chat/numerals.py), now also what the product's answer verification uses: digits, thousands separators, Turkish number words), which closes 5 and 6 of Qwen's gaps and none the wrong way; what is left is wording ("üyeden" for "kişiden", "tarih ve" for "tarih"). An answer that changes an identifier ("E91810702" for "E-91810702") stays wrong. Three questions both models got wrong the same way were checked against the corpus: the golden answers stand (a 2026 amendment of HMK over the older text; a table row read as a sum of three others; an attorney fee tariff taken for the consumer arbitration limit).

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

## In the product

Measured 2026-10-01 (phase 4, step 8) with [eval/answers/chat.py](../../eval/answers/chat.py): all 225 questions through the `synapse-golden` stack's `POST /api/chat`, each in a conversation of its own, as the page asks them: search, the context ([design/answers.md](../design/answers.md)), Qwen3.5-4B on the integrated GPU, the streamed answer, verification. Refusal before generation off, so every question reaches the model ([refusal.md](refusal.md) applies the threshold afterwards). Two answer formats:

- **A**, the benchmark's: the answer as one text, the prompt asking for `[n]` after each sentence.
- **B**, what ships: the answer as a list of sentences, each with the numbers of the sources it rests on, at least one, bounded by the sources shown; the grammar makes it.

Every answer the script scored wrong was read with its question, golden answer and evidence quote; the ones that state the golden answer count as correct (B: 26, among them "en az 7, en çok 15 üyeden" for "en az yedi ve en çok on beş üye" and "75 mg/L" for "≥75 mg/L"; an answer that changes an identifier, "34674941" for "UİP-34674941", stays wrong).

| | A | **B** |
|---|---|---|
| answers with a citation after their sentences | 14 of 171 | **181 of 181** |
| correct, by the script | 120 of 191 (0.628) | 131 (0.686) |
| **correct, by hand** | 144 (0.754) | **157 (0.822)** |
| factual | 53 of 65 | **58** |
| identifier | 50 of 62 | 50 |
| table | 30 of 43 | **35** |
| multi-document | 11 of 21 | **14** |
| answerable refused by the model | 15 | 15 |
| failed (the chat server killed, below) | 8 | 0 |
| unanswerable refused by the model | 31 of 34 | 29 |
| a correct answer's citations cover its evidence (script) | 97 of 120 | 126 of 131 |
| verification: answers written again, sentences removed | 2, 0 | 8, 2 |

Without the 8 questions A lost to the crashes, A has 144 of 183 right (0.787) and B 150 (0.820). B is better on every type but identifiers, where the two are equal; it cites after every sentence, and its citations cover the evidence of 96% of the answers the script scores correct. Its unanswerable refusals are two fewer, which the threshold of 1.0 makes up for ([refusal.md](refusal.md)). The evidence was among the sources given to the model for 0.963 of the answerable questions in both.

**Where B is wrong** (19 answered wrongly): a value from the wrong row or column of a table (6: "15.064,68" for "293,64", the parcel's area for the municipality's share of it), the evidence not among the sources (5, retrieval), an identifier changed or the wrong code (4: a file name given as a document code), a wrong number in running text (3: "bir ay" for "üç ay", "yüzde yirmi" for "yüzde yirmibeş"), and another side of the question answered (1). Verification catches none of these: each wrong number stands somewhere in the sources, or is a number word with a suffix ("yirmisi") that it does not read as a number. And 15 answerable questions are refused with their evidence among the sources, mostly table cells and identifiers.

**Speed** (B, the client's clock, the integrated GPU, one question at a time): sources 4.5 s (90th percentile 5.1), first token 18.4 s (24.4, longest 45.3), whole answer 22.7 s (31.5, longest 47.8). Within the 16 GB tier's budget for the answer (a minute to the first token, two to the end); not for the sources (3 s), which the chat sends after reranking: sending the first stage's order at once is the fix. B writes a little more than A (22.7 against 19.8 s for the whole answer): the sentences' JSON.

**The chat server ran out of memory in run A.** llama-server keeps up to 8 GiB of earlier prompts in host memory by default (`--cache-ram`), and the 5 GB container was OOM-killed four times in an hour, failing the 8 answers in flight. With `--cache-ram 0` (now in the stack and in what synapsectl renders) run B peaked at 584 MiB, with no restart.

## Limits

- 75 questions: one answerable question is 1.5 points; the gap between the models is five to ten times that, the gap between contexts is not.
- Hand scoring is one reader's; the ids re-scored are listed in [eval/answers/README.md](../../eval/answers/README.md).
- The retrieved context is BM25 reranked; the first stage that will ship ([embeddings.md](embeddings.md#choice)) finds more on paraphrased questions, which this run does not use.
- The 75-question runs above have neither verification nor refusal before generation; the product's runs ("In the product") have both.

## Next steps

1. A scorer that also accepts a golden answer's wording varied (a judge that compares the answer's facts, not its words), so the script agrees with the hand scoring; numbers are done.
2. The same bake-off on the paraphrased questions with the shipping first stage.
3. ~~Answer verification measured~~ Done in the product's run (above): 8 answers written again, 2 sentences removed, and none of the 19 wrong answers caught. Next: check each number against the source its own sentence cites, with its unit, and read number words with suffixes.
4. The 15 answerable questions the model refuses with their evidence among its sources: the prompt and the context (table rows, identifiers), measured on the same run.
5. Sources on screen within 3 seconds in the chat: send the first stage's order at once, the reranked order after.
