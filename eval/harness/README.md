# Evaluation harness

Every ADR 0010 metric of the product on the golden set, measured through a running stack's API, and the gates that fail a commit when they drop (phase 4, step 9). Design: [docs/design/evaluation.md](../../docs/design/evaluation.md).

- [run.py](run.py): one measurement. Retrieval on both question sets (`POST /api/search`, reranked: Hit@1, Hit@10, MRR per type), every question through `POST /api/chat` with the product's own settings (correct, cited, refused, failed; every final answer's numbers checked again against the sources it was given), and the time to the sources, the first token and the whole answer. The questions on scanned documents ([scanned.jsonl](../golden/scanned.jsonl)) are measured the same way as a set of their own. Writes `report.json`, `report.md`, `answers.jsonl` and `answers-scanned.jsonl`; with `--baseline`, exits 1 when a gate fails.
- [watch.py](watch.py): the local trigger on the reference machine. It measures the newest commit on `origin/main` and posts the result to GitHub as the commit status `synapse/eval` and a commit comment holding `report.md`.
- `baseline.json`: the report the gates compare with, from a run of this harness on the reference machine; a commit that changes a metric on purpose updates it. Without it a run reports and gates nothing (the first run, which makes it).

## Gates

| Gate | Fails when |
|---|---|
| Retrieval, as written and paraphrased: Hit@1, Hit@10, MRR over all questions | more than 0.01 below the baseline (ADR 0010: "more than 1 point") |
| Unsupported numbers | any number or identifier of a final answer stands in none of its sources |
| Failed answers | any (a model or the API failed) |
| Unanswerable questions refused | fewer than the baseline's, beyond one question (one of 34 is 3 points, and two runs of the model can differ by one) |
| Correct answers (the script's scoring) | more than 0.03 below the baseline (six questions) |
| Scanned documents: Hit@1, Hit@10, MRR; correct answers | more than one question below the baseline, once the baseline has the set |
| Scanned documents: unsupported numbers, failed answers | any |

ADR 0010's v1 targets are reported beside the gates (met or not met); they do not fail a commit, since some are not met yet.

## Running it by hand

```bash
uv run --directory backend python ../eval/harness/run.py --base http://127.0.0.1:8490 \
  --email editor@golden.example --password-file "$PWD/.dev/golden-password" \
  --documents "$PWD/eval/retrieval/work/product/documents.json" --out /tmp/harness \
  --baseline "$PWD/eval/harness/baseline.json" --wait-ready
```

The stack must have the corpus ingested (eval/retrieval/product.py `upload`, which writes the documents file). A whole run takes about two hours on the reference machine, one question at a time: on its integrated GPU two at a time made every answer 2.5 times slower, so the run took longer, not shorter. `--limit N` takes the first N questions of each set, for a quick check.

## The local trigger

Set up once on the reference machine (the mini PC):

```bash
git clone https://github.com/FurkanKocatas/Synapse.git ~/synapse-ci/repo
( crontab -l; echo '*/15 * * * * PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin flock -n $HOME/synapse-ci/lock python3 $HOME/synapse-ci/repo/eval/harness/watch.py >> $HOME/synapse-ci/watch.log 2>&1' ) | crontab -
```

It runs from its own clone, never the development checkout; the clone's `.dev` and `eval/corpus/files` link to the development checkout's (secrets, the stack's tenant, the model files, the corpus). It starts runs only between 08:00 and 21:30 and stops whatever runs at 00:05, so the machine is quiet at night; commits that change only what the measurement does not read (documentation, the web interface under `frontend/`) are marked and not measured; when several commits arrive, only the newest is measured. The corpus is ingested again (about an hour) only when the code or the model that ingestion depends on changed. State: `~/synapse-ci/state` (the last commit measured, the ingestion's fingerprint, every run's report under `runs/<commit>/`), log: `~/synapse-ci/watch.log`. While a run holds `~/synapse-ci/lock`, the `synapse-golden` stack is the harness's: do not use it by hand.

Only commits on `origin/main` are measured, from a clone that fetches nothing else: no fork's or pull request's code ever runs on the machine. A GitHub Actions self-hosted runner was not used for that reason: on a public repository it takes its jobs from workflow files that a pull request can change, and it would run them with Docker, that is root, on the machine.
