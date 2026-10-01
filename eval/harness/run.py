"""Every ADR 0010 metric of a running stack on the golden set, and the gates (phase 4, step 9).

    uv run --directory backend python ../eval/harness/run.py --base URL --email EDITOR \\
        --password-file FILE --documents DOCUMENTS_JSON --out DIR [--baseline FILE] \\
        [--concurrency 2] [--limit N]

Through the stack's API, as users would, with the corpus already ingested
(eval/retrieval/product.py ``upload`` wrote DOCUMENTS_JSON, the product's document ids to the
corpus's):

1. **Retrieval**: each answerable question of both sets (as written, paraphrased) through
   ``POST /api/search``, reranked: Hit@1, Hit@10 and MRR@10 per question type.
2. **Answers**: each question through ``POST /api/chat`` with the product's own settings,
   refusal before generation included: correct (the golden answer in the answer, numbers read
   as numbers), cited, refused, failed; for the unanswerable questions, refused. Every number
   and identifier of every final answer is checked again against the sources it was given
   (synapse.chat.verification): a claim in none of them is an unsupported number.
3. **Speed**: the median and 90th percentile of the time to the sources, to the first token and
   to the whole answer, as the client sees them. One question at a time by default: on the
   reference machine's integrated GPU two at a time made each answer 2.5 times slower (the
   first token after 49.8 s against 18.4), so the whole run took longer, not shorter.

Writes report.json and report.md to ``--out``. With ``--baseline`` (eval/harness/baseline.json)
it applies the gates and exits 1 when one fails:

- a retrieval metric (Hit@1, Hit@10, MRR, all questions, each set) more than 0.01 below the
  baseline (ADR 0010: "more than 1 point");
- any unsupported number in a final answer;
- fewer unanswerable questions refused than the baseline, beyond one question (34 questions:
  one is 3 points, and two runs of the model can differ by one);
- correct answers more than 0.03 below the baseline (six questions), or any failed answer.

The v1 targets of ADR 0010 are reported beside them; they do not fail the run, since some are
not met yet (docs/benchmarks/).
"""

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
sys.path.insert(0, str(EVAL / "retrieval"))
sys.path.insert(0, str(EVAL / "answers"))
sys.path.insert(0, str(EVAL / "golden"))

from chat import ask, judge  # noqa: E402
from product import signed_in, wait  # noqa: E402
from score import QUESTIONS, TYPES, Golden, metrics  # noqa: E402
from synapse.chat.answering import source_text  # noqa: E402
from synapse.chat.verification import check  # noqa: E402
from synapse.knowledge.public import Hit  # noqa: E402

PARAPHRASED = QUESTIONS.parent / "paraphrased.jsonl"
RETRIEVAL_DROP = 0.01
ANSWER_DROP = 0.03
REFUSAL_SLACK = 1
TARGETS = {
    "hit@10, as written": ("retrieval.as_written.all.hit@10", ">=", 0.95),
    "hit@1, as written": ("retrieval.as_written.all.hit@1", ">=", 0.75),
    "identifier hit@1, as written": ("retrieval.as_written.identifier.hit@1", ">=", 0.98),
    "unanswerable refused": ("answers.unanswerable_refused", ">=", 0.90),
    "answerable refused": ("answers.answerable_refused", "<=", 0.05),
    "seconds to the first token, median": ("answers.seconds.first_token.median", "<=", 60.0),
    "seconds to the whole answer, median": ("answers.seconds.answer.median", "<=", 120.0),
}


def load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def parallel[T, R](items: list[T], work: Callable[[T], R], concurrency: int) -> list[R]:
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return list(pool.map(work, items))


def retrieval(
    client: Any, questions: list[dict[str, Any]], documents: dict[str, str], concurrency: int
) -> dict[str, Any]:
    answerable = [q for q in questions if q["type"] != "unanswerable"]

    def search(question: dict[str, Any]) -> tuple[int | None, float]:
        started = time.perf_counter()
        response = client.post(
            "/api/search", json={"query": question["question"], "limit": 10, "rerank": True}
        )
        response.raise_for_status()
        hits = [
            {"doc": documents.get(h["document_id"]), "pages": [h["page_start"], h["page_end"]]}
            for h in response.json()["hits"]
        ]
        rank = Golden(question).rank(list(range(len(hits))), hits)
        return rank, time.perf_counter() - started

    results = parallel(answerable, search, concurrency)
    ranks: dict[str, list[int | None]] = defaultdict(list)
    for question, (rank, _) in zip(answerable, results, strict=True):
        ranks[question["type"]].append(rank)
        ranks["all"].append(rank)
    report: dict[str, Any] = {
        kind: _rounded(metrics(ranks[kind])) for kind in (*TYPES, "all") if ranks[kind]
    }
    report["seconds_median"] = round(statistics.median(s for _, s in results), 2)
    return report


def answers(
    client: Any, questions: list[dict[str, Any]], documents: dict[str, str], concurrency: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    def one(question: dict[str, Any]) -> dict[str, Any]:
        seen = ask(client, question["question"])
        answer = seen.get("answer") or {}
        sources = seen.get("sources") or []
        unsupported: tuple[str, ...] = ()
        if answer.get("status") == "answered":
            texts = [_as_shown(s) for s in sources]
            unsupported = check(answer["text"], texts, list(range(1, len(texts) + 1))).unsupported
        return {
            "id": question["id"],
            "type": question["type"],
            **judge(question, seen, documents),
            "answer": answer.get("text", ""),
            "error": answer.get("error") or seen.get("error"),
            "unsupported": list(unsupported),
            "retried": seen["retried"],
            "stripped": answer.get("stripped", 0),
            "sources_seconds": seen.get("sources_seconds"),
            "first_token_seconds": seen.get("first_token_seconds"),
            "seconds": seen.get("seconds"),
        }

    records = parallel(questions, one, concurrency)
    answerable = [r for r in records if r["type"] != "unanswerable"]
    unanswerable = [r for r in records if r["type"] == "unanswerable"]
    by_type = {
        kind: round(_share([r for r in answerable if r["type"] == kind], "correct"), 3)
        for kind in TYPES
        if any(r["type"] == kind for r in answerable)
    }
    report = {
        "correct": round(_share(answerable, "correct"), 3),
        "correct_by_type": by_type,
        "cited": round(_share(answerable, "cited"), 3),
        "answerable_refused": round(
            sum(r["status"] != "answered" for r in answerable) / max(1, len(answerable)), 3
        ),
        "unanswerable_refused": round(_share(unanswerable, "correct"), 3),
        "unanswerable_refused_count": sum(r["correct"] for r in unanswerable),
        "unanswerable": len(unanswerable),
        "failed": sum(r["status"] == "failed" for r in records),
        "unsupported_numbers": sum(len(r["unsupported"]) for r in records),
        "retried": sum(r["retried"] for r in records),
        "sentences_removed": sum(r["stripped"] for r in records),
        "seconds": {
            name: _spread([r[key] for r in records if r.get(key) is not None])
            for name, key in (
                ("sources", "sources_seconds"),
                ("first_token", "first_token_seconds"),
                ("answer", "seconds"),
            )
        },
    }
    return report, records


def _as_shown(source: dict[str, Any]) -> str:
    """A source as the model saw it (title, pages, headings, text), by the product's own rule."""
    hit = Hit(
        document_id=UUID(source["document_id"]),
        title=source["title"],
        version_id=uuid4(),
        version=source["version"],
        ordinal=source["ordinal"],
        kind="text",
        heading_path=tuple(source["heading_path"]),
        text=source["text"] or "",
        page_start=source["page_start"],
        page_end=source["page_end"],
        context="",
        lexical_rank=None,
        dense_rank=None,
    )
    return source_text(hit)


def gates(report: dict[str, Any], baseline: dict[str, Any]) -> list[dict[str, Any]]:
    """Each gate with its value, its bar and whether it passed."""
    found = []
    for questions in ("as_written", "paraphrased"):
        for metric in ("hit@1", "hit@10", "mrr"):
            path = f"retrieval.{questions}.all.{metric}"
            bar = round(_get(baseline, path) - RETRIEVAL_DROP, 3)
            found.append(_gate(path, _get(report, path), ">=", bar))
    found.append(
        _gate("answers.unsupported_numbers", _get(report, "answers.unsupported_numbers"), "<=", 0)
    )
    found.append(_gate("answers.failed", _get(report, "answers.failed"), "<=", 0))
    refused = "answers.unanswerable_refused_count"
    found.append(
        _gate(refused, _get(report, refused), ">=", _get(baseline, refused) - REFUSAL_SLACK)
    )
    correct = "answers.correct"
    found.append(
        _gate(correct, _get(report, correct), ">=", round(_get(baseline, correct) - ANSWER_DROP, 3))
    )
    return found


def targets(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {**_gate(path, _get(report, path), sign, bar), "name": name}
        for name, (path, sign, bar) in TARGETS.items()
    ]


def markdown(report: dict[str, Any]) -> str:
    lines = [f"**synapse/eval** on `{report['commit'][:7]}`: {report['verdict']}", ""]
    lines += ["| Gate | Value | Bar | |", "|---|---|---|---|"]
    for g in report["gates"]:
        mark = "pass" if g["ok"] else "**fail**"
        lines.append(f"| {g['path']} | {g['value']} | {g['sign']} {g['bar']} | {mark} |")
    lines += ["", "| ADR 0010 target | Value | Target | |", "|---|---|---|---|"]
    for t in report["targets"]:
        mark = "met" if t["ok"] else "**not met**"
        lines.append(f"| {t['name']} | {t['value']} | {t['sign']} {t['bar']} | {mark} |")
    r, a = report["retrieval"], report["answers"]
    lines += [
        "",
        "Retrieval, Hit@1 / Hit@10 (as written; paraphrased): "
        + ", ".join(
            f"{kind} {r['as_written'][kind]['hit@1']:.2f}/{r['as_written'][kind]['hit@10']:.2f}"
            f" ({r['paraphrased'][kind]['hit@1']:.2f}/{r['paraphrased'][kind]['hit@10']:.2f})"
            for kind in (*TYPES, "all")
            if kind in r["as_written"] and kind in r["paraphrased"]
        ),
        f"Answers: correct {a['correct']} (script; "
        + ", ".join(f"{k} {v}" for k, v in a["correct_by_type"].items())
        + f"), cited {a['cited']}, answerable refused {a['answerable_refused']}, unanswerable "
        f"refused {a['unanswerable_refused_count']} of {a['unanswerable']}, retried "
        f"{a['retried']}, sentences removed {a['sentences_removed']}.",
        f"Seconds (median / 90th percentile, {report['concurrency']} at a time): sources "
        f"{a['seconds']['sources']['median']} / {a['seconds']['sources']['p90']}, first token "
        f"{a['seconds']['first_token']['median']} / {a['seconds']['first_token']['p90']}, answer "
        f"{a['seconds']['answer']['median']} / {a['seconds']['answer']['p90']}. "
        f"Run: {report['minutes']} minutes.",
    ]
    return "\n".join(lines) + "\n"


def _gate(path: str, value: float, sign: str, bar: float) -> dict[str, Any]:
    ok = value >= bar if sign == ">=" else value <= bar
    return {"path": path, "value": value, "sign": sign, "bar": bar, "ok": ok}


def _get(data: dict[str, Any], path: str) -> Any:
    for part in path.split("."):
        data = data[part]
    return data


def _rounded(values: dict[str, float]) -> dict[str, float]:
    return {k: round(v, 3) for k, v in values.items()}


def _share(rows: list[dict[str, Any]], key: str) -> float:
    return sum(bool(r[key]) for r in rows) / max(1, len(rows))


def _spread(values: list[float]) -> dict[str, float]:
    if not values:
        return {"median": 0.0, "p90": 0.0}
    ordered = sorted(values)
    return {
        "median": round(statistics.median(ordered), 1),
        "p90": round(ordered[int(0.9 * (len(ordered) - 1))], 1),
    }


def main() -> int:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("--base", required=True)
    options.add_argument("--email", required=True)
    options.add_argument("--password-file", type=Path, required=True)
    options.add_argument("--documents", type=Path, required=True)
    options.add_argument("--out", type=Path, required=True)
    options.add_argument("--baseline", type=Path)
    options.add_argument("--commit", default="")
    options.add_argument("--concurrency", type=int, default=1)
    options.add_argument("--limit", type=int, default=0, help="the first N questions of each set")
    options.add_argument(
        "--wait-ready", action="store_true", help="first wait until every document is processed"
    )
    args = options.parse_args()
    started = time.monotonic()
    documents = json.loads(args.documents.read_text(encoding="utf-8"))["documents"]
    written, paraphrased = load(QUESTIONS), load(PARAPHRASED)
    if args.limit:
        written, paraphrased = written[: args.limit], paraphrased[: args.limit]
    password = args.password_file.read_text(encoding="utf-8").strip()
    client = signed_in(args.base, args.email, password)
    try:
        if args.wait_ready:
            corpus = json.loads(args.documents.read_text(encoding="utf-8"))
            wait(client, corpus["collection"], len(corpus["documents"]))
        report: dict[str, Any] = {
            "commit": args.commit,
            "concurrency": args.concurrency,
            "questions": len(written),
            "retrieval": {
                "as_written": retrieval(client, written, documents, args.concurrency),
                "paraphrased": retrieval(client, paraphrased, documents, args.concurrency),
            },
        }
        report["answers"], records = answers(client, written, documents, args.concurrency)
    finally:
        client.close()
    report["minutes"] = round((time.monotonic() - started) / 60, 1)
    report["targets"] = targets(report)
    report["gates"] = []
    if args.baseline:
        report["gates"] = gates(report, json.loads(args.baseline.read_text(encoding="utf-8")))
    failed = [g for g in report["gates"] if not g["ok"]]
    report["verdict"] = "no baseline" if not args.baseline else ("fail" if failed else "pass")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    with (args.out / "answers.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    (args.out / "report.md").write_text(markdown(report), encoding="utf-8")
    print(markdown(report))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
