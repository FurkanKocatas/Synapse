"""Every ADR 0010 metric of a running stack on the golden set, and the gates (phase 4, step 9).

    uv run --directory backend python ../eval/harness/run.py --base URL --email EDITOR \\
        --password-file FILE --documents DOCUMENTS_JSON --out DIR [--baseline FILE] \\
        [--concurrency 2] [--limit N]

Through the stack's API, as users would, with the corpus already ingested
(eval/retrieval/product.py ``upload`` wrote DOCUMENTS_JSON, the product's document ids to the
corpus's):

1. **Retrieval**: each answerable question of both sets (as written, paraphrased) through
   ``POST /api/search``, reranked: Hit@1, Hit@10 and MRR@10 per question type, on the evidence's
   page; and, reported beside them, the share whose first hit is in the evidence's document
   (``document_hit@1``: the right document, whatever its page; questions on several documents
   left out).
2. **Answers**: each question through ``POST /api/chat`` with the product's own settings,
   refusal before generation included: correct (the golden answer in the answer, numbers read
   as numbers), cited, refused, failed; for the unanswerable questions, refused. Every number
   and identifier of every final answer is checked again against the sources it was given
   (synapse.chat.verification): a claim in none of them is an unsupported number.
3. **Metadata**: the kind, date and number suggested for each corpus document when it was read
   (knowledge/metadata.py), and whether the kind is the one its manifest title names. Reported,
   not gated: written to metadata.jsonl.
4. **Speed**: the median and 90th percentile of the time to the sources, to the first token and
   to the whole answer, as the client sees them. One question at a time by default: on the
   reference machine's integrated GPU two at a time made each answer 2.5 times slower (the
   first token after 49.8 s against 18.4), so the whole run took longer, not shorter.

Writes report.json and report.md to ``--out``. With ``--baseline`` (eval/harness/baseline.json)
it applies the gates and exits 1 when one fails:

- a retrieval metric (Hit@1, Hit@10, MRR, all questions, each set) more than 0.01 below the
  baseline (ADR 0010: "more than 1 point"); 0.02 after a fresh ingestion (``--fresh-ingestion``),
  since two ingestions of the same code differ by that much (HNSW graphs and GPU vectors are not
  bit for bit the same: 0.011 to 0.015 measured on 2026-10-01);
- any unsupported number in a final answer;
- fewer unanswerable questions refused than the baseline, beyond one question (34 questions:
  one is 3 points, and two runs of the model can differ by one);
- correct answers more than 0.03 below the baseline (six questions), or any failed answer.

The v1 targets of ADR 0010 are reported beside them; they do not fail the run, since some are
not met yet (docs/benchmarks/).

The scanned-document questions (eval/golden/scanned.jsonl: evidence on pages that go to OCR) are
measured as a set of their own, retrieval and answers, so that OCR's effect on search and answers
shows and the golden set's own numbers stay comparable. Their gates apply once the baseline has
them: a retrieval metric or correct answers more than one question below it; any unsupported
number or failed answer fails at once.
"""

import argparse
import csv
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
from check import fold  # noqa: E402
from product import signed_in, wait  # noqa: E402
from score import QUESTIONS, TYPES, Golden, metrics  # noqa: E402
from synapse.chat.answering import source_text  # noqa: E402
from synapse.chat.verification import check  # noqa: E402
from synapse.knowledge.metadata import suggest  # noqa: E402
from synapse.knowledge.public import Hit  # noqa: E402

MANIFEST = EVAL / "corpus" / "manifest.csv"
PARAPHRASED = QUESTIONS.parent / "paraphrased.jsonl"
SCANNED = QUESTIONS.parent / "scanned.jsonl"
RETRIEVAL_DROP = 0.01
RETRIEVAL_DROP_FRESH = 0.02
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

    def search(question: dict[str, Any]) -> tuple[int | None, float, dict[str, Any]]:
        started = time.perf_counter()
        response = client.post(
            "/api/search", json={"query": question["question"], "limit": 10, "rerank": True}
        )
        response.raise_for_status()
        found = response.json()["hits"]
        hits: list[dict[str, Any]] = [
            {"doc": documents.get(h["document_id"]), "pages": [h["page_start"], h["page_end"]]}
            for h in found
        ]
        rank = Golden(question).rank(list(range(len(hits))), hits)
        scores = [h["rerank_score"] for h in found if h["rerank_score"] is not None]
        record = {
            "id": question["id"],
            "type": question["type"],
            "rank": rank,
            "document_first": _document_first(question, hits),
            "best": round(max(scores), 3) if scores else None,
            "hits": [[h["doc"], *h["pages"]] for h in hits],
        }
        return rank, time.perf_counter() - started, record

    results = parallel(answerable, search, concurrency)
    ranks: dict[str, list[int | None]] = defaultdict(list)
    first: dict[str, list[bool]] = defaultdict(list)
    for question, (rank, _, record) in zip(answerable, results, strict=True):
        for kind in (question["type"], "all"):
            ranks[kind].append(rank)
            # One hit cannot hold several documents: those questions have no first document.
            if question["type"] != "multi_document":
                first[kind].append(record["document_first"])
    report: dict[str, Any] = {
        kind: _rounded(metrics(ranks[kind]))
        | ({"document_hit@1": round(sum(first[kind]) / len(first[kind]), 3)} if first[kind] else {})
        for kind in (*TYPES, "all")
        if ranks[kind]
    }
    report["seconds_median"] = round(statistics.median(s for _, s, _ in results), 2)
    report["records"] = [record for _, _, record in results]
    return report


def _document_first(question: dict[str, Any], hits: list[dict[str, Any]]) -> bool:
    """Whether the first hit is in a document of the evidence (one evidence piece only)."""
    documents = [{doc for doc, _ in piece} for piece in Golden(question).pieces]
    return len(documents) == 1 and bool(hits) and hits[0]["doc"] in documents[0]


def answers(
    client: Any, questions: list[dict[str, Any]], documents: dict[str, str], concurrency: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    def one(question: dict[str, Any]) -> dict[str, Any]:
        seen = ask(client, question["question"])
        answer = seen.get("answer") or {}
        sources = seen.get("sources") or []
        texts = [_as_shown(s) for s in sources]
        unsupported: tuple[str, ...] = ()
        if answer.get("status") == "answered":
            unsupported = check(answer["text"], texts, list(range(1, len(texts) + 1))).unsupported
        return {
            "id": question["id"],
            "type": question["type"],
            **judge(question, seen, documents),
            **shown(question, sources),
            "answer": answer.get("text", ""),
            "error": answer.get("error") or seen.get("error"),
            "unsupported": list(unsupported),
            "retried": seen["retried"],
            "stripped": answer.get("stripped", 0),
            "sources_seconds": seen.get("sources_seconds"),
            "first_token_seconds": seen.get("first_token_seconds"),
            "seconds": seen.get("seconds"),
            # What the model was given, as it saw it: checks on the answers (a guard against
            # answering from another organisation's document, say) are tried on these offline.
            "sources": texts,
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
        "answerable": len(answerable),
        # Why answerable questions went unanswered: their evidence in the chunks the model was
        # given (the model held back) or not (the context lacked it).
        "refused_quoted": sum(r["status"] != "answered" and r["quoted"] for r in answerable),
        "refused_answer_shown": sum(
            r["status"] != "answered" and r["answer_shown"] for r in answerable
        ),
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


def metadata(
    client: Any, collection_id: str, documents: dict[str, str]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """What was suggested for each document, and the kind its manifest title names (the same
    rule on a title a person wrote: the uploaded name is the file's, "10092026_eylul2026_...")."""
    with MANIFEST.open(encoding="utf-8") as handle:
        titles = {row["id"]: row["title"] for row in csv.DictReader(handle)}
    records = [
        {
            "doc": documents[d["id"]],
            "title": d["title"],
            "kind": d.get("kind"),
            "named_kind": suggest(titles.get(documents[d["id"]], ""), "").kind,
            "document_date": d.get("document_date"),
            "reference": d.get("reference"),
        }
        for d in client.get(f"/api/collections/{collection_id}/documents").json()
        if d["id"] in documents
    ]
    named = [r for r in records if r["named_kind"]]
    report = {
        "documents": len(records),
        "kind": sum(r["kind"] is not None for r in records),
        "date": sum(r["document_date"] is not None for r in records),
        "reference": sum(r["reference"] is not None for r in records),
        "kind_named_by_title": len(named),
        "kind_as_named": sum(r["kind"] == r["named_kind"] for r in named),
    }
    return report, sorted(records, key=lambda r: r["doc"])


def shown(question: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, bool]:
    """Whether the evidence was in the chunks themselves, not only on their pages (``found``):
    ``quoted`` when its quote stands in one of them (each part's, for a multi-document question),
    ``answer_shown`` when the golden answer does (looser: a chunk boundary can cut a quote)."""
    texts = [fold(source.get("text") or "") for source in sources]
    quotes = [fold(item["quote"]) for item in question.get("evidence", [])]
    parts = question.get("answer_parts") or ([question["answer"]] if question.get("answer") else [])
    if question["type"] == "multi_document":
        quoted = bool(quotes) and all(any(q in t for t in texts) for q in quotes)
    else:
        quoted = any(q in t for q in quotes for t in texts)
    answer_shown = bool(parts) and all(any(fold(p) in t for t in texts) for p in parts)
    return {"quoted": quoted, "answer_shown": answer_shown}


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


def gates(
    report: dict[str, Any], baseline: dict[str, Any], *, fresh: bool = False
) -> list[dict[str, Any]]:
    """Each gate with its value, its bar and whether it passed."""
    found = []
    for questions in ("as_written", "paraphrased"):
        for metric in ("hit@1", "hit@10", "mrr"):
            path = f"retrieval.{questions}.all.{metric}"
            drop = RETRIEVAL_DROP_FRESH if fresh else RETRIEVAL_DROP
            bar = round(_get(baseline, path) - drop, 3)
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
    return found + scanned_gates(report, baseline)


def scanned_gates(report: dict[str, Any], baseline: dict[str, Any]) -> list[dict[str, Any]]:
    """The scanned-document set's gates: about 30 questions, so one question's worth of slack."""
    if "answers_scanned" not in report:
        return []
    answers = report["answers_scanned"]
    found = [
        _gate(f"answers_scanned.{key}", answers[key], "<=", 0)
        for key in ("unsupported_numbers", "failed")
    ]
    if "answers_scanned" not in baseline:
        return found
    one = 1 / max(1, answers["answerable"])
    for path in (
        *(f"retrieval.scanned.all.{m}" for m in ("hit@1", "hit@10", "mrr")),
        "answers_scanned.correct",
    ):
        found.append(_gate(path, _get(report, path), ">=", round(_get(baseline, path) - one, 3)))
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
        + f"), cited {a['cited']}, answerable refused {a['answerable_refused']} (evidence quoted "
        f"in the model's chunks {a['refused_quoted']}, the answer in them "
        f"{a['refused_answer_shown']}), unanswerable "
        f"refused {a['unanswerable_refused_count']} of {a['unanswerable']}, retried "
        f"{a['retried']}, sentences removed {a['sentences_removed']}.",
        "Document-level Hit@1, the right document first (as written; paraphrased): "
        + ", ".join(
            f"{kind} {r['as_written'][kind]['document_hit@1']:.2f}"
            f" ({r['paraphrased'][kind]['document_hit@1']:.2f})"
            for kind in (*TYPES, "all")
            if "document_hit@1" in r["as_written"].get(kind, {})
            and "document_hit@1" in r["paraphrased"].get(kind, {})
        ),
        *_scanned_line(report),
        *_metadata_line(report),
        f"Seconds (median / 90th percentile, {report['concurrency']} at a time): sources "
        f"{a['seconds']['sources']['median']} / {a['seconds']['sources']['p90']}, first token "
        f"{a['seconds']['first_token']['median']} / {a['seconds']['first_token']['p90']}, answer "
        f"{a['seconds']['answer']['median']} / {a['seconds']['answer']['p90']}. "
        f"Run: {report['minutes']} minutes.",
    ]
    return "\n".join(lines) + "\n"


def _scanned_line(report: dict[str, Any]) -> list[str]:
    if "answers_scanned" not in report:
        return []
    r, a = report["retrieval"]["scanned"]["all"], report["answers_scanned"]
    return [
        f"Scanned documents ({a['answerable']} answerable, {a['unanswerable']} unanswerable): "
        f"Hit@1 / Hit@10 {r['hit@1']:.2f}/{r['hit@10']:.2f}, correct {a['correct']}, cited "
        f"{a['cited']}, answerable refused {a['answerable_refused']}, unanswerable refused "
        f"{a['unanswerable_refused_count']}."
    ]


def _metadata_line(report: dict[str, Any]) -> list[str]:
    if "metadata" not in report:
        return []
    m = report["metadata"]
    return [
        f"Metadata suggested ({m['documents']} documents): a kind for {m['kind']}, a date for "
        f"{m['date']}, a number for {m['reference']}; the kind its manifest title names for "
        f"{m['kind_as_named']} of the {m['kind_named_by_title']} whose title names one."
    ]


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
    options.add_argument(
        "--fresh-ingestion", action="store_true", help="the corpus was just ingested again"
    )
    args = options.parse_args()
    started = time.monotonic()
    corpus = json.loads(args.documents.read_text(encoding="utf-8"))
    documents = corpus["documents"]
    written, paraphrased = load(QUESTIONS), load(PARAPHRASED)
    scanned = load(SCANNED) if SCANNED.exists() else []
    if args.limit:
        written, paraphrased = written[: args.limit], paraphrased[: args.limit]
        scanned = scanned[: args.limit]
    password = args.password_file.read_text(encoding="utf-8").strip()
    client = signed_in(args.base, args.email, password)
    try:
        if args.wait_ready:
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
        report["metadata"], metadata_records = metadata(client, corpus["collection"], documents)
        scanned_records: list[dict[str, Any]] = []
        if scanned:
            report["retrieval"]["scanned"] = retrieval(client, scanned, documents, args.concurrency)
            report["answers_scanned"], scanned_records = answers(
                client, scanned, documents, args.concurrency
            )
    finally:
        client.close()
    report["minutes"] = round((time.monotonic() - started) / 60, 1)
    report["targets"] = targets(report)
    report["gates"] = []
    if args.baseline:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        report["gates"] = gates(report, baseline, fresh=args.fresh_ingestion)
    report["fresh_ingestion"] = args.fresh_ingestion
    failed = [g for g in report["gates"] if not g["ok"]]
    report["verdict"] = "no baseline" if not args.baseline else ("fail" if failed else "pass")
    write(
        args.out,
        report,
        {
            "answers": records,
            "answers-scanned": scanned_records,
            "metadata": metadata_records,
        },
    )
    print(markdown(report))
    return 1 if failed else 0


def write(out: Path, report: dict[str, Any], answered: dict[str, list[dict[str, Any]]]) -> None:
    """The report, and every question's retrieval and answer in files of their own."""
    out.mkdir(parents=True, exist_ok=True)
    rows = {
        f"retrieval-{name}": report["retrieval"][name].pop("records")
        for name in report["retrieval"]
    }
    for name, records in (rows | answered).items():
        with (out / f"{name}.jsonl").open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    (out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    (out / "report.md").write_text(markdown(report), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
