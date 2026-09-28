"""Measure the page quality check on the evaluation corpus with two-fold cross-validation.

Born-digital PDFs are split in two by position; a model trained on one half scores the other
half, so every clean page is judged by a model that never saw it. Scanned PDFs are scored by
both models. Reported: the share of clean pages flagged (false positives) and what is flagged
in the scanned documents.

Usage: uv run --directory backend python ../eval/quality/calibrate.py
"""

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_char_model import born_digital, page_texts, pdf_rows, train
from synapse.knowledge.quality import MIN_LETTERS, CharModel, Quality, assess


def summary(values: list[float]) -> str:
    q = statistics.quantiles(values, n=100, method="inclusive")
    return f"p1={q[0]:.2f} p5={q[4]:.2f} p50={q[49]:.2f} p95={q[94]:.2f}"


def score(model: CharModel, rows: list[dict[str, str]]) -> dict[str, list[Quality]]:
    return {row["id"]: [assess(text, model) for text in page_texts(row)] for row in rows}


def main() -> None:
    rows = pdf_rows()
    clean = born_digital(rows)
    scanned = [row for row in rows if row["is_scanned"] == "yes"]
    folds = [clean[0::2], clean[1::2]]
    held_out: dict[str, list[Quality]] = {}
    scanned_scores: dict[str, list[list[Quality]]] = {}
    for k in (0, 1):
        model = train(folds[1 - k])
        held_out.update(score(model, folds[k]))
        for doc, pages in score(model, scanned).items():
            scanned_scores.setdefault(doc, []).append(pages)

    pages = [q for qs in held_out.values() for q in qs]
    judged = [q for q in pages if q.letters >= MIN_LETTERS]
    flagged = {doc: sum(q.needs_ocr for q in qs) for doc, qs in held_out.items()}
    print(f"clean pages: {len(pages)}, judged by char score: {len(judged)}")
    print(f"  char score {summary([q.char_score for q in judged])}")
    print(f"  artefacts  {summary([q.artefacts for q in pages])}")
    total = sum(flagged.values())
    print(f"  flagged: {total} ({100 * total / len(pages):.1f}%)")
    print(f"  by document: { {d: n for d, n in flagged.items() if n} }")
    for doc, both in scanned_scores.items():
        text_pages = [q for q in both[0] if q.letters > 0]
        marks = [sum(q.needs_ocr for q in fold) for fold in both]
        print(f"scanned {doc}: {len(both[0])} pages, {len(text_pages)} with text, flagged {marks}")


if __name__ == "__main__":
    main()
