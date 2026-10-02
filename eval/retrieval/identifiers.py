"""Identifiers after reranking: does putting the chunks that hold the question's identifiers
first lift identifier Hit@1 (ADR 0010: 0.98), and what does it cost the other questions?

    uv run --directory backend python ../eval/retrieval/identifiers.py fetch --base URL \\
        --email EDITOR --password-file FILE [--documents DOCUMENTS_JSON]
    uv run --directory backend python ../eval/retrieval/identifiers.py score

``fetch`` asks the stack's ``POST /api/search`` once per answerable question of both sets (as
written, paraphrased), reranked, the first 15, and keeps every hit with its text and score in
work/product/reranked-<set>.jsonl (holding the harness's lock, ~/synapse-ci/lock). The stack's
document ids map to the corpus's through ``--documents``: product.py's upload writes it, and
the harness's clone has the one for the stack as it is now. ``score``
reorders those saved hits by each variant and scores them as product.py does: Hit@1, Hit@10
and MRR@10 per question type. Nothing is searched again, so variants cost nothing to try.
"""

import argparse
import fcntl
import json
import re
import sys
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from product import OUT, signed_in  # noqa: E402
from score import QUESTIONS, TYPES, Golden, metrics  # noqa: E402
from synapse.knowledge.entities import extract  # noqa: E402
from synapse.knowledge.turkish import lower  # noqa: E402

LOCK = Path.home() / "synapse-ci" / "lock"
SETS = {"as_written": QUESTIONS, "paraphrased": QUESTIONS.parent / "paraphrased.jsonl"}
LIMIT = 15
# A token with a digit in it, as lexical search reads identifiers (knowledge/search.py).
TOKEN = re.compile(r"[\w./-]*\d[\w./-]*")
YEAR = re.compile(r"(19|20)\d\d")
MIN_TOKEN = 4

type Hits = list[dict[str, Any]]


def fetch(base: str, email: str, password: str, documents: Path) -> None:
    mapping = json.loads(documents.read_text(encoding="utf-8"))["documents"]
    LOCK.parent.mkdir(exist_ok=True)
    with LOCK.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        client = signed_in(base, email, password)
        try:
            for name, path in SETS.items():
                with (OUT / f"reranked-{name}.jsonl").open("w", encoding="utf-8") as out:
                    for line in path.read_text(encoding="utf-8").splitlines():
                        question = json.loads(line)
                        if question["type"] == "unanswerable":
                            continue
                        response = client.post(
                            "/api/search",
                            json={"query": question["question"], "limit": LIMIT, "rerank": True},
                        )
                        response.raise_for_status()
                        hits = [
                            {
                                "document_id": h["document_id"],
                                "doc": mapping.get(h["document_id"]),
                                "pages": [h["page_start"], h["page_end"]],
                                "title": h["title"],
                                "heading_path": h["heading_path"],
                                "text": h["text"],
                                "score": h["rerank_score"],
                            }
                            for h in response.json()["hits"]
                        ]
                        record = {"id": question["id"], "type": question["type"], "hits": hits}
                        out.write(json.dumps(record, ensure_ascii=False) + "\n")
                print(name, "saved")
        finally:
            client.close()


def identifiers(text: str, *, years: bool) -> set[str]:
    """The question's identifiers: tokens with a digit (four characters or more), and the
    normalised values of its typed entities (dates, law and decision numbers, articles,
    amounts, parcels), so "3 Haziran 2014" finds "03.06.2014"."""
    folded = lower(text)
    tokens = {t.strip(".-/") for t in TOKEN.findall(folded)}
    found = {t for t in tokens if len(t) >= MIN_TOKEN}
    found |= {f"{e.kind}:{e.value}" for e in extract(text)}
    if not years:
        found = {t for t in found if not YEAR.fullmatch(t)}
    return found


def held(hit: dict[str, Any], wanted: set[str], *, whole: bool) -> int:
    """How many of the question's identifiers the chunk holds, in its title, headings or text:
    anywhere, or (``whole``) as a token of its own ("2014" not in "20145")."""
    text = " ".join([hit["title"], *hit["heading_path"], hit["text"]])
    folded = lower(text)
    values = {f"{e.kind}:{e.value}" for e in extract(text)}

    def holds(token: str) -> bool:
        if not whole:
            return token in folded
        return re.search(rf"(?<!\w){re.escape(token)}(?!\w)", folded) is not None

    return sum(1 for w in wanted if (w in values if ":" in w else holds(w)))


def variant(
    *, years: bool, margin: float | None, whole: bool = False
) -> Callable[[str, Hits], list[int]]:
    """Hits holding more of the question's identifiers first, the reranker's order among
    equals; with a margin, only among the hits scored within it of the best."""

    def order(question: str, hits: Hits) -> list[int]:
        wanted = identifiers(question, years=years)
        indices = list(range(len(hits)))
        scores = [h["score"] for h in hits if h["score"] is not None]
        # Not reranked (the reranker did not answer): nothing to break ties of.
        if not wanted or not scores:
            return indices
        best = max(scores)
        close = [
            i
            for i in indices
            if margin is None
            or (hits[i]["score"] is not None and hits[i]["score"] >= best - margin)
        ]
        rest = [i for i in indices if i not in close]
        close.sort(key=lambda i: -held(hits[i], wanted, whole=whole))
        return close + rest

    return order


VARIANTS: dict[str, Callable[[str, Hits], list[int]]] = {
    "reranker": lambda _question, hits: list(range(len(hits))),
    "ids": variant(years=True, margin=None),
    "ids-no-years": variant(years=False, margin=None),
    "ids, margin 3": variant(years=True, margin=3.0),
    "ids-no-years, margin 3": variant(years=False, margin=3.0),
    "ids-no-years, margin 2": variant(years=False, margin=2.0),
    "ids-no-years, margin 1": variant(years=False, margin=1.0),
    "whole, no years, margin 3": variant(years=False, margin=3.0, whole=True),
    "whole, no years": variant(years=False, margin=None, whole=True),
}


def score() -> None:
    for name, path in SETS.items():
        questions = {
            q["id"]: q for q in (json.loads(line) for line in path.read_text().splitlines())
        }
        records = [
            json.loads(line)
            for line in (OUT / f"reranked-{name}.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        print(f"\n{name}: Hit@1/Hit@10 per type, MRR@10")
        header = "".join(f"{t[:10]:>12}" for t in (*TYPES, "all"))
        print(f"{'variant':<26}{header}{'mrr':>8}")
        for label, order in VARIANTS.items():
            ranks: dict[str, list[int | None]] = defaultdict(list)
            for record in records:
                question = questions[record["id"]]
                hits = record["hits"]
                ordered = order(question["question"], hits)[:10]
                rank = Golden(question).rank(ordered, hits)
                ranks[record["type"]].append(rank)
                ranks["all"].append(rank)
            cells = "".join(
                f"{metrics(ranks[t])['hit@1']:>6.3f}/{metrics(ranks[t])['hit@10']:.2f}"
                for t in (*TYPES, "all")
            )
            print(f"{label:<26}{cells}{metrics(ranks['all'])['mrr']:>8.3f}")


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = options.add_subparsers(dest="command", required=True)
    fetching = commands.add_parser("fetch")
    fetching.add_argument("--base", required=True)
    fetching.add_argument("--email", required=True)
    fetching.add_argument("--password-file", type=Path, required=True)
    fetching.add_argument("--documents", type=Path, default=OUT / "documents.json")
    commands.add_parser("score")
    args = options.parse_args()
    if args.command == "fetch":
        fetch(args.base, args.email, args.password_file.read_text().strip(), args.documents)
    else:
        score()


if __name__ == "__main__":
    main()
