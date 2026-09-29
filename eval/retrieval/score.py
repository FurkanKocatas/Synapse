"""Retrieval quality on the golden set: lexical, dense and fused rankings (README.md).

    uv run --directory backend python ../eval/retrieval/score.py [--parser light] [--misses RUN]
                                                                 [--dump]

A question is answered at rank k when the top k chunks cover every piece of its evidence: a
chunk covers a piece when it is from that document and its pages include the evidence's page
(or a page where the same quote occurs, ``also``). A multi-document question needs all its
pieces. Unanswerable questions are left out here; refusing them is the answer step's job.

Runs:

- ``bm25``: BM25 (k1 1.2, b 0.75) over Turkish-lower-cased words, plus identifiers kept whole
  ("2026/16", "E-81912396-105.04") so a number is not only matched digit group by digit group.
- ``bm25-prefix5``: the same with words cut to their first five letters, a crude but known
  strong stand-in for Turkish lemmas (suffixes carry case and possession).
- one run per embedded model in work/emb/<parser>/ (embed.py): cosine similarity.
- ``ids+bm25-prefix5``: exact identifier lookup first (ADR 0010, query rule 2): the typed
  entities of the question (knowledge/entities.py: dates, decision, law and article numbers,
  amounts, parcels) looked up in the chunks' entities; chunks holding more of them first, in
  BM25 order among equals, then the rest of the BM25 ranking. A question without an entity
  gets the BM25 ranking unchanged.
- ``rrf:A+B``: reciprocal rank fusion of two runs (k 60), ranks only, never scores.

Metrics per question type and overall: Hit@1, Hit@10, MRR@10. Every run ranks 50 candidates;
``--dump`` writes them to work/runs/<parser>/<run>.json for rerank.py, whose reranked runs in
work/runs/<parser>/extra/ are scored as runs of their own.
"""

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from synapse.knowledge.entities import extract
from synapse.knowledge.turkish import lower

HERE = Path(__file__).resolve().parent
WORK = HERE / "work"
QUESTIONS = HERE.parent / "golden" / "questions.jsonl"
WORD = re.compile(r"\w+")
IDENTIFIER = re.compile(r"[\w./-]*\d[\w./-]*")
MIN_IDENTIFIER = 4
PREFIX = 5
DEPTH = 10
CANDIDATES = 50
# How deep the BM25 ranking goes to order the chunks an identifier lookup finds.
TIE_DEPTH = 1000
RRF_K = 60
K1, B = 1.2, 0.75
TYPES = ("factual", "identifier", "table", "multi_document")


def tokens(text: str, prefix: int | None = None) -> list[str]:
    folded = lower(text)
    words = WORD.findall(folded)
    if prefix:
        words = [w if any(ch.isdigit() for ch in w) else w[:prefix] for w in words]
    ids = [t.strip(".-/") for t in IDENTIFIER.findall(folded)]
    return words + [t for t in ids if len(t) >= MIN_IDENTIFIER and not t.isdigit()]


class Bm25:
    def __init__(self, texts: list[str], prefix: int | None = None) -> None:
        self.prefix = prefix
        self.docs = [Counter(tokens(t, prefix)) for t in texts]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.average = sum(self.lengths) / len(self.docs)
        self.postings: dict[str, list[int]] = defaultdict(list)
        for index, doc in enumerate(self.docs):
            for term in doc:
                self.postings[term].append(index)
        n = len(self.docs)
        self.idf = {
            t: math.log(1 + (n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.postings.items()
        }

    def search(self, query: str, depth: int = CANDIDATES) -> list[int]:
        scores: Counter[int] = Counter()
        for term in set(tokens(query, self.prefix)):
            for index in self.postings.get(term, ()):
                tf = self.docs[index][term]
                norm = tf + K1 * (1 - B + B * self.lengths[index] / self.average)
                scores[index] += self.idf[term] * tf * (K1 + 1) / norm
        return [index for index, _ in scores.most_common(depth)]


class Identifiers:
    def __init__(self, texts: list[str]) -> None:
        self.index: dict[tuple[str, str], set[int]] = defaultdict(set)
        for index, text in enumerate(texts):
            for entity in extract(text):
                self.index[(entity.kind, entity.value)].add(index)

    def search(self, query: str, lexical: list[int], depth: int = CANDIDATES) -> list[int]:
        wanted = {(entity.kind, entity.value) for entity in extract(query)}
        held: Counter[int] = Counter()
        for key in wanted:
            for index in self.index.get(key, ()):
                held[index] += 1
        position = {index: rank for rank, index in enumerate(lexical)}
        first = sorted(held, key=lambda i: (-held[i], position.get(i, len(position))))
        return (first + [i for i in lexical if i not in held])[:depth]


def fuse(*rankings: list[int], depth: int = CANDIDATES) -> list[int]:
    scores: Counter[int] = Counter()
    for ranking in rankings:
        for rank, index in enumerate(ranking):
            scores[index] += 1 / (RRF_K + rank + 1)
    return [index for index, _ in scores.most_common(depth)]


@dataclass
class Golden:
    question: dict[str, Any]

    @property
    def pieces(self) -> list[set[tuple[str, int]]]:
        return [
            {(e["doc"], e["page"])} | {(a["doc"], a["page"]) for a in e.get("also", [])}
            for e in self.question["evidence"]
        ]

    def rank(self, ranking: list[int], chunks: list[dict[str, Any]]) -> int | None:
        """The rank (1-based) at which every piece is covered, or None in the top ten."""
        open_pieces = self.pieces
        for position, index in enumerate(ranking[:DEPTH], start=1):
            c = chunks[index]
            first, last = c["pages"]
            open_pieces = [
                piece
                for piece in open_pieces
                if not any(doc == c["doc"] and first <= page <= last for doc, page in piece)
            ]
            if not open_pieces:
                return position
        return None


def metrics(ranks: list[int | None]) -> dict[str, float]:
    n = len(ranks)
    return {
        "hit@1": sum(1 for r in ranks if r is not None and r <= 1) / n,
        "hit@5": sum(1 for r in ranks if r is not None and r <= 5) / n,  # noqa: PLR2004
        "hit@10": sum(1 for r in ranks if r is not None) / n,
        "mrr": sum(1 / r for r in ranks if r is not None) / n,
    }


def dense_runs(parser: str, queries: int) -> dict[str, np.ndarray]:
    digest = hashlib.sha256(QUESTIONS.read_bytes()).hexdigest()
    runs = {}
    for directory in sorted((WORK / "emb" / parser).glob("*")):
        if (directory / "chunks.npy").exists():
            passages = np.load(directory / "chunks.npy")
            questions = np.load(directory / "questions.npy")
            meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
            if questions.shape[0] != queries or meta.get("questions_sha256") != digest:
                raise SystemExit(
                    f"{directory.name}: embedded for another version of the questions; "
                    f"run embed.py {directory.name} --questions-only"
                )
            runs[directory.name] = np.argsort(-(questions @ passages.T), axis=1)[:, :CANDIDATES]
    return runs


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("--parser", default="light")
    options.add_argument("--misses", help="print the questions this run misses at rank 10")
    options.add_argument("--dump", action="store_true", help="write every run's candidates")
    args = options.parse_args()
    chunks = [
        json.loads(line)
        for line in (WORK / f"chunks-{args.parser}.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    all_questions = [
        json.loads(line)
        for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    texts = [c["text"] for c in chunks]
    lexical = {"bm25": Bm25(texts), "bm25-prefix5": Bm25(texts, PREFIX)}
    rankings: dict[str, list[list[int]]] = {
        name: [index.search(q["question"]) for q in all_questions]
        for name, index in lexical.items()
    }
    deep = [lexical["bm25-prefix5"].search(q["question"], TIE_DEPTH) for q in all_questions]
    exact = Identifiers(texts)
    rankings["ids+bm25-prefix5"] = [
        exact.search(q["question"], ranking) for q, ranking in zip(all_questions, deep, strict=True)
    ]
    for name, order in dense_runs(args.parser, len(all_questions)).items():
        rankings[name] = [list(map(int, row)) for row in order]
        rankings[f"rrf:bm25-prefix5+{name}"] = [
            fuse(a, b) for a, b in zip(rankings["bm25-prefix5"], rankings[name], strict=True)
        ]
    runs = WORK / "runs" / args.parser
    for extra in sorted((runs / "extra").glob("*.json")):
        rankings[extra.stem] = json.loads(extra.read_text(encoding="utf-8"))["rankings"]
    if args.dump:
        runs.mkdir(parents=True, exist_ok=True)
        for name, ranking in rankings.items():
            (runs / f"{name}.json").write_text(json.dumps({"rankings": ranking}), encoding="utf-8")

    answerable = [
        (i, Golden(q)) for i, q in enumerate(all_questions) if q["type"] != "unanswerable"
    ]
    print(f"{len(chunks)} chunks ({args.parser}); {len(answerable)} answerable questions")
    header = f"{'run':<34}" + "".join(f"{t[:10]:>12}" for t in (*TYPES, "all"))
    print("Hit@1 / Hit@10 by type; MRR@10 last")
    print(header + f"{'mrr':>8}")
    for name, ranking in rankings.items():
        by_type: dict[str, list[int | None]] = defaultdict(list)
        for i, golden in answerable:
            r = golden.rank(ranking[i], chunks)
            by_type[golden.question["type"]].append(r)
            by_type["all"].append(r)
        cells = "".join(
            f"{metrics(by_type[t])['hit@1']:>6.2f}/{metrics(by_type[t])['hit@10']:.2f}"
            for t in (*TYPES, "all")
        )
        print(f"{name:<34}{cells}{metrics(by_type['all'])['mrr']:>8.3f}")
        if name == args.misses:
            for i, golden in answerable:
                if golden.rank(ranking[i], chunks) is None:
                    q = golden.question
                    top = chunks[ranking[i][0]] if ranking[i] else {}
                    print(f"  miss {q['id']} {q['type']}: {q['question'][:90]}")
                    print(f"      want {sorted(golden.pieces[0])[:3]}; top {top.get('id')}")


if __name__ == "__main__":
    main()
