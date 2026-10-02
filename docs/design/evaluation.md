# Evaluation harness and its gates: design

Status: implemented, 2026-10-01 (phase 4, step 9). Decisions: [ADR 0010](../adr/0010-rag-pipeline.md) (evaluation gates), Furkan's choice of 2026-10-01 to measure on the reference machine with a local trigger rather than a GitHub Actions runner. Code and how to run it: [eval/harness/](../../eval/harness/README.md).

## What is measured

The golden set ([eval/golden/](../../eval/golden/README.md): 225 questions, 34 of them unanswerable, and a paraphrased copy of the 191 answerable ones) against the `synapse-golden` stack, which holds the 97 corpus documents ingested by the product itself, with the model servers on the integrated GPU. Everything goes through the API a user's browser calls:

| Part | How | Metrics |
|---|---|---|
| Retrieval | `POST /api/search`, reranked, both question sets | Hit@1, Hit@10, MRR@10, per question type |
| Answers | `POST /api/chat`, each question in a conversation of its own, the product's settings (refusal before generation at its threshold) | correct and cited (the script's scoring), refused, failed; unanswerable questions refused; numbers and identifiers of every final answer in none of its sources |
| Speed | the client's clock, one question at a time | median and 90th percentile to the sources, the first token, the whole answer |

The script's scoring of answers (the golden answer, numbers read as numbers, inside the answer) is stricter than a reader: by hand the shipping configuration got 157 of 191 right, the script 131 ([answers.md](../benchmarks/answers.md#in-the-product)). It is the same on every run, which is what a gate needs; benchmarks that decide something are still read by hand.

## Gates

A gate compares the run with `eval/harness/baseline.json` at the same commit and fails the commit when retrieval drops by more than a point (Hit@1, Hit@10 or MRR on either set), when a final answer holds an unsupported number, when an answer fails, when fewer unanswerable questions are refused (beyond one question of 34, the difference two runs of the model can show), or when correct answers drop by more than 3 points. ADR 0010's v1 targets (Hit@10 0.95, Hit@1 0.75, identifier Hit@1 0.98, refusal 0.90, false refusal 0.05, the latency budget) are reported with every run as met or not met; they gate nothing yet, since some are not met.

A change meant to move a metric updates the baseline in the same commit, with the run that shows it.

## Where it runs, and why there

On the reference machine, by a local trigger ([watch.py](../../eval/harness/watch.py)) that cron starts every 15 minutes: the models need its GPU (on GitHub's runners, CPU only, the answers alone would take more than three hours), and its numbers are the ones the product is measured by.

- **Only `origin/main`**, from a clone of its own: no code from a fork or a pull request runs on the machine. A GitHub Actions self-hosted runner would take its jobs from workflow files a pull request can change and run them with Docker, which is root on the machine; one wrong approval would be enough.
- **Results on GitHub**: the commit status `synapse/eval` (pending while measuring, then success or failure with a one-line summary) and a commit comment holding the report's tables.
- **Quiet at night**: runs start between 08:00 and 21:30 only, and whatever runs is stopped at 00:05.
- **Less work**: only the newest unmeasured commit is measured; a commit that changes only what the measurement does not read (documentation, the web interface) is marked and skipped; the corpus is ingested again (an hour) only when a file that ingestion depends on changed (the parser, OCR, chunking, entities, lexical terms, the embedding adapter, the model files' pins, the corpus list); otherwise the stack is upgraded in place (`synapse knowledge reindex` after the migrations). One question at a time: two at a time made each answer 2.5 times slower on the integrated GPU.
- **Failures**: a run that cannot finish (a build, the stack, the deadline) is retried once on the next trigger, then marked `error` on the commit.

A whole run takes about two hours; with a fresh ingestion, about three.
