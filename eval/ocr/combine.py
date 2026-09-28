"""Tesseract for the text, RapidOCR for a second reading of the identifiers.

No single engine reaches the identifier target, but the two miss different identifiers: RapidOCR
reads digits well and Turkish letters badly, Tesseract the reverse. This scores, from outputs
run.py already wrote, what a combination would give:

- ``agreement``: the base engine's identifiers split by whether RapidOCR read the same token,
  with the precision of each part. Disagreement is a candidate signal for flagging uncertain
  numbers in answers.
- ``combined``: the base text plus RapidOCR's identifiers the base lacks, scored like an engine
  (per-page means, worst 10% in brackets). In the product those extra identifiers would be
  search terms, not text shown to a reader or a model.

Usage: uv run --directory backend python ../eval/ocr/combine.py [BASE ...]
"""

import json
import statistics
import sys
from collections import Counter

from score import CONDITIONS, REAL_TRUTH, WORK, is_identifier, page_scores, tokens

SECOND = "rapidocr-latin"
DEFAULT_BASES = ("tesseract-best-tur", "tesseract-best-tur+eng")


def output(engine: str, page: str, condition: str) -> str:
    return (WORK / "out" / engine / f"{page}.{condition}.txt").read_text()


def identifiers(text: str) -> Counter[str]:
    return Counter(t for t in tokens(text) if is_identifier(t))


def cell(values: list[float]) -> str:
    worst = sorted(values)[: max(1, len(values) // 10)]
    return f"{statistics.fmean(values):.3f} ({statistics.fmean(worst):.3f})"


def main() -> None:
    bases = sys.argv[1:] or list(DEFAULT_BASES)
    pages = [p["name"] for p in json.loads((WORK / "pages.json").read_text())]
    print(f"{'condition':9} {'base':24} {'agreed: n, precision':22} {'disputed: n, precision':24}")
    print(f"{'':34} word_f1 / tr_recall / id_recall of base + {SECOND} identifiers")
    for condition in CONDITIONS:
        for base in bases:
            counts: Counter[str] = Counter()
            scores: dict[str, list[float]] = {}
            for page in pages:
                truth_text = (WORK / "truth" / f"{page}.txt").read_text()
                truth = identifiers(truth_text)
                base_text = output(base, page, condition)
                first, second = identifiers(base_text), identifiers(output(SECOND, page, condition))
                agreed, disputed = first & second, first - second
                counts["agreed"] += agreed.total()
                counts["agreed_right"] += (agreed & truth).total()
                counts["disputed"] += disputed.total()
                counts["disputed_right"] += (disputed & (truth - agreed)).total()
                combined = base_text + "\n" + " ".join((second - first).elements())
                for key, value in page_scores(truth_text, combined).items():
                    if value is not None:
                        scores.setdefault(key, []).append(value)
            parts = [
                f"{counts[part]:4d}, {counts[part + '_right'] / counts[part]:.3f}"
                for part in ("agreed", "disputed")
            ]
            print(f"{condition:9} {base:24} {parts[0]:22} {parts[1]:24}")
            print(
                f"{'':34} {cell(scores['word_f1'])} / {cell(scores['tr_recall'])} / "
                f"{cell(scores['id_recall'])}"
            )
    real(bases)


def real(bases: list[str]) -> None:
    print()
    print("Real scans: word_f1 / tr_recall / id_recall, base alone -> base + identifiers")
    for truth_file in sorted(REAL_TRUTH.glob("*.txt")):
        truth_text = truth_file.read_text()
        for base in bases:
            base_text = output(base, truth_file.stem, "real")
            second = identifiers(output(SECOND, truth_file.stem, "real"))
            combined = base_text + "\n" + " ".join((second - identifiers(base_text)).elements())
            before, after = page_scores(truth_text, base_text), page_scores(truth_text, combined)
            print(
                f"  {truth_file.stem} {base:24} "
                + "  ".join(
                    f"{before[k] or 0:.3f} -> {after[k] or 0:.3f}"
                    for k in ("word_f1", "tr_recall", "id_recall")
                )
            )


if __name__ == "__main__":
    main()
