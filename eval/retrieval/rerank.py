"""Rerank a run's candidates with a cross-encoder (README.md; ADR 0010, query rule 5).

    uv run --project eval/retrieval python eval/retrieval/rerank.py RUN [--parser light]
                                                                   [--top 30] [--threads 6]

Reads work/runs/<parser>/RUN.json (score.py --dump), scores the top ``--top`` candidates of
every question against it with the reranker, and writes them in the reranker's order, followed
by the rest, to work/runs/<parser>/extra/RUN+<reranker>@<top>.json, with the median and 90th
percentile seconds per question (all its candidates in one batch). Every candidate's licence is
allowed by ADR 0016 without review, and none needs remote code.
"""

import argparse
import json
import statistics
import time
from pathlib import Path

import torch
from sentence_transformers import CrossEncoder

HERE = Path(__file__).resolve().parent
WORK = HERE / "work"
QUESTIONS = HERE.parent / "golden" / "questions.jsonl"
MAX_TOKENS = 512
RERANKERS = {"bge-m3-reranker": "BAAI/bge-reranker-v2-m3"}


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("run")
    options.add_argument("--reranker", choices=sorted(RERANKERS), default="bge-m3-reranker")
    options.add_argument("--parser", default="light")
    options.add_argument("--top", type=int, default=30)
    options.add_argument("--threads", type=int, default=6)
    args = options.parse_args()
    torch.set_num_threads(args.threads)
    runs = WORK / "runs" / args.parser
    rankings = json.loads((runs / f"{args.run}.json").read_text(encoding="utf-8"))["rankings"]
    chunks = [
        json.loads(line)["text"]
        for line in (WORK / f"chunks-{args.parser}.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    questions = [
        json.loads(line)["question"]
        for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    model = CrossEncoder(RERANKERS[args.reranker], device="cpu", max_length=MAX_TOKENS)
    reranked, seconds = [], []
    for question, ranking in zip(questions, rankings, strict=True):
        top = ranking[: args.top]
        started = time.perf_counter()
        scores = model.predict([(question, chunks[i]) for i in top], batch_size=len(top) or 1)
        seconds.append(time.perf_counter() - started)
        order = [i for _, i in sorted(zip(scores, top, strict=True), key=lambda pair: -pair[0])]
        reranked.append(order + ranking[args.top :])
    (runs / "extra").mkdir(parents=True, exist_ok=True)
    name = f"{args.run}+{args.reranker}@{args.top}"
    timing = {
        "median_seconds": round(statistics.median(seconds), 2),
        "p90_seconds": round(statistics.quantiles(seconds, n=10)[-1], 2),
        "threads": args.threads,
    }
    (runs / "extra" / f"{name}.json").write_text(
        json.dumps({"rankings": reranked, **timing}), encoding="utf-8"
    )
    print(json.dumps({"run": name, **timing}))


if __name__ == "__main__":
    main()
