"""Refusal before generation, calibrated: the reranker's best score for each question (step 8).

    uv run --directory backend python ../eval/answers/refusal.py --base URL --email EDITOR \\
        --password-file FILE [--questions FILE]

ADR 0010, query rule 6: when the best calibrated score is below the answerability threshold,
reply "not found" without calling the model. The reranker's score is the calibrated one (fused
scores have no absolute meaning). Every question of the golden set goes through a running
stack's ``POST /api/search`` (eval/retrieval/product.py's stack, reranked); its best score,
whether the search found the evidence, and the question's type go to
eval/answers/work/refusal-<questions>.jsonl. Printed: the scores' spread for answerable and
unanswerable questions, and for candidate thresholds the share of unanswerable questions
refused, of answerable ones refused, and of answerable ones refused although the evidence was
found, against ADR 0010's targets (refuse at least 90%, refuse at most 5% wrongly).
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "retrieval"))
from product import signed_in  # noqa: E402
from score import QUESTIONS, Golden  # noqa: E402

OUT = HERE / "work"


def collect(base: str, email: str, password: str, questions_file: Path) -> list[dict[str, object]]:
    client = signed_in(base, email, password)
    records = []
    try:
        for line in questions_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            question = json.loads(line)
            response = client.post(
                "/api/search", json={"query": question["question"], "limit": 10, "rerank": True}
            )
            response.raise_for_status()
            hits = response.json()["hits"]
            scores = [h["rerank_score"] for h in hits if h["rerank_score"] is not None]
            found = None
            if question["type"] != "unanswerable":
                chunks = [
                    {"doc": h["document_id"], "pages": [h["page_start"], h["page_end"]]}
                    for h in hits
                ]
                ranked = Golden(question).rank(list(range(len(chunks))), _by_corpus(chunks))
                found = ranked is not None
            records.append(
                {
                    "id": question["id"],
                    "type": question["type"],
                    "best": max(scores) if scores else None,
                    "found": found,
                }
            )
    finally:
        client.close()
    return records


_MAPPING: dict[str, str] = {}


def _by_corpus(chunks: list[dict[str, object]]) -> list[dict[str, object]]:
    """Hits with the product's document ids as the corpus's (eval/retrieval/product.py)."""
    if not _MAPPING:
        path = HERE.parent / "retrieval" / "work" / "product" / "documents.json"
        _MAPPING.update(json.loads(path.read_text(encoding="utf-8"))["documents"])
    return [{**c, "doc": _MAPPING.get(str(c["doc"]))} for c in chunks]


def report(records: list[dict[str, object]]) -> None:
    unanswerable = [r["best"] for r in records if r["type"] == "unanswerable"]
    answerable = [r for r in records if r["type"] != "unanswerable"]
    found = [r["best"] for r in answerable if r["found"]]
    for name, values in (
        ("unanswerable", unanswerable),
        ("answerable", [r["best"] for r in answerable]),
        ("answerable, evidence found", found),
    ):
        present = sorted(v for v in values if v is not None)  # type: ignore[type-var]
        if present:
            quartiles = statistics.quantiles(present, n=4)
            print(
                f"{name:<28} n {len(values):>3}  min {present[0]:7.2f}  q1 {quartiles[0]:7.2f}  "
                f"median {quartiles[1]:7.2f}  q3 {quartiles[2]:7.2f}  max {present[-1]:7.2f}"
            )
    every = [r["best"] for r in records if r["best"] is not None]
    candidates = sorted({round(float(v) * 2) / 2 for v in every})  # type: ignore[arg-type]
    print(
        f"{'threshold':>9} {'refused unanswerable':>21} "
        f"{'refused answerable':>19} {'refused, found':>15}"
    )
    for threshold in candidates:
        print(
            f"{threshold:>9.1f} {_refused(unanswerable, threshold):>21.2f} "
            f"{_refused([r['best'] for r in answerable], threshold):>19.2f} "
            f"{_refused(found, threshold):>15.2f}"
        )


def _refused(values: list[object], threshold: float) -> float:
    """The share refused at this threshold: no reranked hit, or the best score below it."""
    below = sum(1 for v in values if v is None or float(v) < threshold)  # type: ignore[arg-type]
    return below / max(1, len(values))


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("--base", required=True)
    options.add_argument("--email", required=True)
    options.add_argument("--password-file", type=Path, required=True)
    options.add_argument("--questions", type=Path, default=QUESTIONS)
    args = options.parse_args()
    password = args.password_file.read_text(encoding="utf-8").strip()
    records = collect(args.base, args.email, password, args.questions)
    OUT.mkdir(exist_ok=True)
    with (OUT / f"refusal-{args.questions.stem}.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    report(records)


if __name__ == "__main__":
    main()
