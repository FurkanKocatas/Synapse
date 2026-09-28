"""Score the OCR benchmark outputs against the pages' own text layers.

Metrics per engine and image condition (mean over pages, with the worst decile):

- ``cer``: character error rate after whitespace normalisation. Sensitive to reading order, so
  multi-column and table pages score worse than their words deserve.
- ``word_f1``: F1 over the multiset of words, independent of order.
- ``tr_recall``: share of the truth's words with Turkish letters (ç ğ ı İ ö ş ü) that the OCR
  output contains exactly. These are where Turkish OCR usually fails.
- ``id_recall``: share of the truth's identifiers found exactly. An identifier is a token of at
  least 4 characters of which at least half the letters and digits are digits: "2026/35",
  "15.03.2025", "5393", "E-83913885", "₺2.500.000". A wrong decision number or amount is the
  most harmful OCR error for search and answers. Page and row numbers (single digits) and
  footnote marks glued to words ("algoritma2") are not identifiers.

Apostrophes and dashes are normalised on both sides, as search normalises them too.
- ``sec/page``: median time per page, one thread.

Usage: uv run --directory backend python ../eval/ocr/score.py [--worst ENGINE CONDITION]
"""

import argparse
import json
import re
import statistics
import unicodedata
from collections import Counter
from pathlib import Path

from rapidfuzz.distance import Levenshtein

HERE = Path(__file__).resolve().parent
WORK = HERE / "work"
REAL_TRUTH = HERE / "real"  # hand-verified transcriptions of real scanned pages
CONDITIONS = ("clean", "scan", "poor")
TURKISH = set("çğıöşüÇĞİÖŞÜ")
_EDGE = "()[]{}<>\"'«»“”‘’.,;:!?*•"


APOSTROPHES = str.maketrans(
    {"’": "'", "‘": "'", "`": "'", "\u00b4": "'"}
    | dict.fromkeys("\u2010\u2011\u2012\u2013\u2014\u2212", "-")
)
MIN_ID_LENGTH = 4


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFC", text).translate(APOSTROPHES)
    text = re.sub(r"-\n(?=\w)", "", text)  # words hyphenated across lines
    return " ".join(text.split())


def tokens(text: str) -> list[str]:
    return [t for t in (w.strip(_EDGE) for w in normalise(text).split()) if t]


def is_identifier(token: str) -> bool:
    alnum = [ch for ch in token if ch.isalnum()]
    digits = sum(ch.isdigit() for ch in alnum)
    return len(token) >= MIN_ID_LENGTH and digits > 0 and digits * 2 >= len(alnum)


def recall(truth: list[str], found: Counter[str]) -> float | None:
    if not truth:
        return None
    wanted = Counter(truth)
    return sum(min(n, found[t]) for t, n in wanted.items()) / sum(wanted.values())


def page_scores(truth_text: str, ocr_text: str) -> dict[str, float | None]:
    truth, ocr = normalise(truth_text), normalise(ocr_text)
    truth_tokens, ocr_tokens = tokens(truth_text), tokens(ocr_text)
    found = Counter(ocr_tokens)
    common = sum((Counter(truth_tokens) & found).values())
    precision = common / len(ocr_tokens) if ocr_tokens else 0.0
    word_recall = common / len(truth_tokens) if truth_tokens else 0.0
    f1 = 2 * precision * word_recall / (precision + word_recall) if common else 0.0
    return {
        "cer": min(1.0, Levenshtein.distance(truth, ocr) / max(1, len(truth))),
        "word_f1": f1,
        "tr_recall": recall([t for t in truth_tokens if TURKISH & set(t)], found),
        "id_recall": recall([t for t in truth_tokens if is_identifier(t)], found),
    }


def summarise(values: list[float], *, higher_is_better: bool) -> str:
    mean = statistics.fmean(values)
    ordered = sorted(values, reverse=not higher_is_better)
    worst = ordered[: max(1, len(ordered) // 10)]
    return f"{mean:6.3f} (worst 10%: {statistics.fmean(worst):.3f})"


def main() -> None:
    options = argparse.ArgumentParser()
    options.add_argument("--worst", nargs=2, metavar=("ENGINE", "CONDITION"))
    args = options.parse_args()
    pages = json.loads((WORK / "pages.json").read_text())
    engines = sorted(p.name for p in (WORK / "out").iterdir() if (p / "timings.json").exists())
    if args.worst:
        engine, condition = args.worst
        scored = []
        for page in pages:
            truth = (WORK / "truth" / f"{page['name']}.txt").read_text()
            ocr = (WORK / "out" / engine / f"{page['name']}.{condition}.txt").read_text()
            scored.append((page_scores(truth, ocr)["word_f1"], page["name"]))
        for f1, name in sorted(scored)[:8]:
            print(f"{f1:.3f} {name}")
        return
    real_table(engines)
    print()
    print(
        f"{'engine':24} {'cond':5}  {'cer':26} {'word_f1':26} {'tr_recall':26} "
        f"{'id_recall':26} sec/page"
    )
    for engine in engines:
        timings = json.loads((WORK / "out" / engine / "timings.json").read_text())
        for condition in CONDITIONS:
            metrics: dict[str, list[float]] = {}
            for page in pages:
                truth = (WORK / "truth" / f"{page['name']}.txt").read_text()
                ocr = (WORK / "out" / engine / f"{page['name']}.{condition}.txt").read_text()
                for key, value in page_scores(truth, ocr).items():
                    if value is not None:
                        metrics.setdefault(key, []).append(value)
            seconds = statistics.median(
                t for name, t in timings.items() if name.endswith(f".{condition}")
            )
            print(
                f"{engine:24} {condition:5}  "
                f"{summarise(metrics['cer'], higher_is_better=False):26} "
                f"{summarise(metrics['word_f1'], higher_is_better=True):26} "
                f"{summarise(metrics['tr_recall'], higher_is_better=True):26} "
                f"{summarise(metrics['id_recall'], higher_is_better=True):26} {seconds:.2f}"
            )


def real_table(engines: list[str]) -> None:
    truths = sorted(REAL_TRUTH.glob("*.txt"))
    print(f"Real scans ({len(truths)} hand-verified pages): cer / word_f1 / tr_recall / id_recall")
    for engine in engines:
        cells = []
        for truth_file in truths:
            ocr_file = WORK / "out" / engine / f"{truth_file.stem}.real.txt"
            if not ocr_file.exists():
                cells.append(f"{truth_file.stem}: not run")
                continue
            scores = page_scores(truth_file.read_text(), ocr_file.read_text())
            cells.append(
                f"{truth_file.stem[:7]}: "
                + " / ".join("-" if v is None else f"{v:.3f}" for v in scores.values())
            )
        print(f"  {engine:24} " + " | ".join(cells))


if __name__ == "__main__":
    main()
