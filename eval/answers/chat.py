"""Grounded answers end to end through the product (phase 4, step 8): the golden set asked
through a running stack's ``POST /api/chat``.

    uv run --directory backend python ../eval/answers/chat.py --base URL --email EDITOR \\
        --password-file FILE [--questions FILE] [--limit N] [--seed 7] [--scores FILE]

The stack is eval/retrieval/product.py's, with the corpus uploaded and its chat model running.
Each question is asked in a conversation of its own and goes through everything a user's does:
search, refusal before generation, the context, the streamed answer, its verification. Recorded
per question: the outcome (answered, not_found, insufficient, failed), the answer, the sources
as corpus documents and pages (eval/retrieval/work/product/documents.json), the citations,
whether the answer was retried or had sentences removed, and the times to the sources, to the
first token and to the whole answer, as the client sees them.

Scored as answer.py scores: an answerable question is correct when it was answered and the
answer contains the golden answer (or every answer part) after Turkish lower-casing, plain
apostrophes and dashes and numbers written as digits; cited when its cited sources cover every
piece of evidence; an unanswerable one is right when it was not answered.

With ``--scores`` (refusal.py's output: each question's best reranker score) it also prints
what refusal before generation would make of these answers at each threshold. For that the
server runs with ``SYNAPSE_CHAT_REFUSE_BELOW=-100``, so every question reaches the model.

Writes eval/answers/work/chat-<questions>.jsonl and prints the summary.
"""

import argparse
import json
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx2

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "retrieval"))
sys.path.insert(0, str(HERE.parent / "golden"))

from check import fold  # noqa: E402
from product import signed_in  # noqa: E402
from score import QUESTIONS, Golden  # noqa: E402
from synapse.chat.numerals import numeric  # noqa: E402

OUT = HERE / "work"
DOCUMENTS = HERE.parent / "retrieval" / "work" / "product" / "documents.json"


def ask(client: httpx2.Client, question: str) -> dict[str, Any]:
    started = time.perf_counter()
    seen: dict[str, Any] = {"deltas": 0, "retried": False}
    name = ""
    with client.stream("POST", "/api/chat", json={"question": question}) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data = json.loads(line.removeprefix("data: "))
                elapsed = round(time.perf_counter() - started, 2)
                if name == "sources":
                    # The first are on screen first; the answer rests on the last.
                    seen["sources"] = data["sources"]
                    seen["warnings"] = data["warnings"]
                    seen.setdefault("sources_seconds", elapsed)
                elif name == "delta":
                    seen.setdefault("first_token_seconds", elapsed)
                    seen["deltas"] += 1
                elif name == "retrying":
                    seen["retried"] = True
                    seen["unsupported"] = data["unsupported"]
                elif name == "answer":
                    seen["answer"] = data
                    seen["seconds"] = elapsed
                elif name == "error":
                    seen["error"] = data
    return seen


def judge(
    question: dict[str, Any], seen: dict[str, Any], documents: dict[str, str]
) -> dict[str, Any]:
    answer = seen.get("answer") or {"status": "failed", "text": "", "citations": []}
    answered = answer["status"] == "answered"
    if question["type"] == "unanswerable":
        return {"status": answer["status"], "correct": not answered, "cited": True}
    text = numeric(fold(answer["text"]))
    parts = question.get("answer_parts") or [question["answer"]]
    correct = answered and all(numeric(fold(part)) in text for part in parts)
    sources = seen.get("sources") or []
    cited = [sources[n - 1] for n in answer["citations"] if 1 <= n <= len(sources)]
    return {
        "status": answer["status"],
        "correct": correct,
        "cited": correct and _covers(question, cited, documents),
        "found": _covers(question, sources, documents),
    }


def _covers(
    question: dict[str, Any], sources: list[dict[str, Any]], documents: dict[str, str]
) -> bool:
    chunks = [
        {"doc": documents.get(s["document_id"]), "pages": [s["page_start"], s["page_end"]]}
        for s in sources
    ]
    return Golden(question).rank(list(range(len(chunks))), chunks) is not None


def share(rows: list[dict[str, Any]], test: Any) -> float:
    return sum(1 for r in rows if test(r)) / max(1, len(rows))


def summary(records: list[dict[str, Any]]) -> None:
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_type[r["type"]].append(r)
    for kind, rows in sorted(by_type.items()):
        statuses = defaultdict(int)
        for r in rows:
            statuses[r["status"]] += 1
        print(
            f"{kind:<15} n {len(rows):>3}  correct {sum(r['correct'] for r in rows):>3}  "
            f"cited {sum(r['cited'] for r in rows):>3}  {dict(statuses)}"
        )
    answerable = [r for r in records if r["type"] != "unanswerable"]
    unanswerable = [r for r in records if r["type"] == "unanswerable"]
    print(
        f"answerable correct {share(answerable, lambda r: r['correct']):.3f}, "
        f"refused {share(answerable, lambda r: r['status'] != 'answered'):.3f}, "
        f"evidence among the sources {share(answerable, lambda r: r.get('found')):.3f}; "
        f"unanswerable refused {share(unanswerable, lambda r: r['correct']):.3f}; "
        f"retried {sum(r['retried'] for r in records)}, "
        f"sentences removed {sum(r['stripped'] for r in records)}"
    )
    for key in ("sources_seconds", "first_token_seconds", "seconds"):
        values = sorted(r[key] for r in records if r.get(key) is not None)
        if values:
            p90 = values[int(0.9 * (len(values) - 1))]
            median = statistics.median(values)
            print(f"{key:<20} median {median:6.1f}  p90 {p90:6.1f}  max {values[-1]:6.1f}")


def thresholds(records: list[dict[str, Any]], scores_file: Path) -> None:
    best = {}
    for line in scores_file.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        best[row["id"]] = row["best"]
    values = sorted({round(v * 2) / 2 for v in best.values() if v is not None})
    answerable = [r for r in records if r["type"] != "unanswerable"]
    unanswerable = [r for r in records if r["type"] == "unanswerable"]
    header = ("threshold", 9), ("unanswerable refused", 21), ("answerable refused", 19)
    print(" ".join(f"{name:>{width}}" for name, width in header), f"{'correct':>8}")
    for threshold in [min(values) - 1, *values]:
        refused = _refusal(best, threshold)
        print(
            f"{threshold:>9.1f} {share(unanswerable, refused):>21.3f} "
            f"{share(answerable, refused):>19.3f} "
            f"{share(answerable, lambda r: r['correct'] and not refused(r)):>8.3f}"  # noqa: B023
        )


def _refusal(best: dict[str, float | None], threshold: float) -> Any:
    def refused(r: dict[str, Any]) -> bool:
        score = best.get(r["id"])
        return r["status"] != "answered" or score is None or score < threshold

    return refused


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("--base", required=True)
    options.add_argument("--email", required=True)
    options.add_argument("--password-file", type=Path, required=True)
    options.add_argument("--questions", type=Path, default=QUESTIONS)
    options.add_argument("--limit", type=int, default=0)
    options.add_argument("--seed", type=int, default=7)
    options.add_argument("--scores", type=Path)
    args = options.parse_args()
    questions = [
        json.loads(line)
        for line in args.questions.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.limit:
        random.Random(args.seed).shuffle(questions)  # noqa: S311  (a sample, not a secret)
        questions = questions[: args.limit]
    documents = json.loads(DOCUMENTS.read_text(encoding="utf-8"))["documents"]
    password = args.password_file.read_text(encoding="utf-8").strip()
    client = signed_in(args.base, args.email, password)
    OUT.mkdir(exist_ok=True)
    out = OUT / f"chat-{args.questions.stem}{f'-{args.limit}' if args.limit else ''}.jsonl"
    records = []
    try:
        with out.open("w", encoding="utf-8") as handle:
            for question in questions:
                seen = ask(client, question["question"])
                answer = seen.get("answer") or {}
                record = {
                    "id": question["id"],
                    "type": question["type"],
                    **judge(question, seen, documents),
                    "answer": answer.get("text", ""),
                    "citations": answer.get("citations", []),
                    "error": answer.get("error") or seen.get("error"),
                    "retried": seen["retried"],
                    "unsupported": seen.get("unsupported", []),
                    "stripped": answer.get("stripped", 0),
                    "warnings": seen.get("warnings", []),
                    "sources": [
                        [documents.get(s["document_id"]), s["page_start"], s["page_end"]]
                        for s in seen.get("sources") or []
                    ],
                    "sources_seconds": seen.get("sources_seconds"),
                    "first_token_seconds": seen.get("first_token_seconds"),
                    "seconds": seen.get("seconds"),
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                records.append(record)
                print(
                    json.dumps(
                        {k: record[k] for k in ("id", "status", "correct", "cited", "seconds")}
                    ),
                    flush=True,
                )
    finally:
        client.close()
    summary(records)
    if args.scores:
        thresholds(records, args.scores)


if __name__ == "__main__":
    main()
