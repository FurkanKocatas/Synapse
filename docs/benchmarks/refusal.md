# Refusal on unanswerable questions: calibrating refusal before generation

Status: **decided**, 2026-10-01 (phase 4, step 8): `chat_refuse_below` is 1.0. ADR 0010, query rule 6: when the best calibrated score is below the answerability threshold, the answer is "not found in your documents" and the chat model is not called; the target is to refuse at least 90% of unanswerable questions while refusing at most 5% of answerable ones. Scripts: [eval/answers/refusal.py](../../eval/answers/refusal.py) and [chat.py](../../eval/answers/chat.py) ([README](../../eval/answers/README.md#through-the-product)). Design: [answers.md](../design/answers.md).

## Method

The golden set's 225 questions ([eval/golden/](../../eval/golden/README.md)): 191 answerable, 34 unanswerable. Its unanswerable questions are near misses by design: each asks about something the corpus is close to but does not hold (the consumer arbitration limit, where the corpus has an attorney fee tariff; a council decision's number, where the corpus has another decision of the same council). They are harder to refuse than the questions a user asks of the wrong document collection.

Every question goes through the `synapse-golden` stack's API (the 97 corpus documents ingested, the model servers on the reference machine's integrated GPU, [search.md](../design/search.md#measured)):

1. `POST /api/search`, reranked: the best reranker score of each question (bge-reranker-v2-m3's logit over the fusion's first 15).
2. `POST /api/chat` with refusal before generation off (`SYNAPSE_CHAT_REFUSE_BELOW=-100`), so every question reaches the model: whether the model itself says the sources do not suffice.
3. Each threshold applied afterwards to both: a question is refused when its best score is below the threshold or when the model did not answer it.

## The reranker's score alone

| | n | lowest | median | highest |
|---|---|---|---|---|
| unanswerable | 34 | -4.86 | 1.29 | 7.43 |
| answerable | 190 | -0.14 | 6.98 | 10.61 |
| factual | 65 | -0.14 | 7.53 | 9.60 |
| identifier | 62 | 1.24 | 7.10 | 10.61 |
| table | 42 | 1.89 | 6.20 | 10.48 |
| multi-document | 21 | 1.69 | 6.52 | 8.48 |

One answerable search of 225 came back without reranking (g8-15; the same search reranked afterwards, its best score 8.17), and is left out.

Refused before generation at each threshold:

| threshold | unanswerable refused | answerable refused |
|---|---|---|
| -1.0 | 7 of 34 (0.21) | 0 |
| -0.5 | 10 (0.29) | 0 |
| 0.0 | 12 (0.35) | 1 (g7-06) |
| 1.0 | 16 (0.47) | 2 |
| 2.0 | 25 (0.74) | 7 |
| 3.0 | 27 (0.79) | 15 |
| 4.0 | 30 (0.88) | 26 |
| 4.5 | 31 (0.91) | 33 (0.17) |

**The two overlap too much for the score to decide alone**: refusing 90% of the unanswerable questions before generation would refuse 17% of the answerable ones. The near misses score like answers, because their sources are about the same thing. Before generation, the score can only take away the clearly unrelated questions; the rest is the model's to judge.

## With the model

The answer run of [answers.md](answers.md#in-the-product) (the answer as cited sentences, every question reaching the model), each threshold applied afterwards; correct answers scored by hand:

| threshold | unanswerable refused | answerable refused | correct answers |
|---|---|---|---|
| none | 29 of 34 (0.853) | 15 (0.079) | 157 of 191 (0.822) |
| 0.0 | 30 (0.882) | 15 (0.079) | 157 (0.822) |
| **1.0** | **31 (0.912)** | **16 (0.084)** | **157 (0.822)** |
| 1.5 | 31 (0.912) | 17 (0.089) | 156 (0.817) |
| 2.0 | 32 (0.941) | 20 (0.105) | 154 (0.806) |
| 2.5 | 33 (0.971) | 24 (0.126) | 151 (0.791) |
| 4.5 | 33 (0.971) | 44 (0.230) | 135 (0.707) |

The model refuses most unanswerable questions by itself (29 of 34): told that the sources must suffice, it says so when they do not. Of the five it answered, two score below 1.0 (u-15, the consumer arbitration limit answered with an attorney fee; u-22), and the threshold takes them; the one answerable question it then refuses as well (g8-24) had been answered wrongly anyway.

**Decision: 1.0.** It meets the target on unanswerable questions (0.912 against at least 0.90) and costs no correct answer. It does not meet the target on false refusals (0.084 against at most 0.05), and no threshold can: 15 of the 16 are the model's own refusals, all with the evidence among the sources it was given (table cells and identifiers, mostly: a proposal number, a cost estimate, a list's row 318). That is the model being cautious, to be worked on in the prompt and the context, not in the threshold. Three unanswerable questions still get an answer, each with a figure from a neighbouring document (another municipality's staff count, another year's budget, another fee); their best scores are 1.59 to 4.58, among the answerable questions'.

## Limits

- 34 unanswerable questions: one is 3 points. The threshold sits between two of them (0.96 and 1.19) and below every answerable question but two (g7-06 at -0.14, which the model refuses anyway, and g8-24 at 0.88); on a customer's golden set it is calibrated again.
- One reranker, one model: the score is bge-reranker-v2-m3's logit, and the model's refusals are Qwen3.5-4B's under this prompt. Either changing means measuring again.
