"""OCR measured against the target of docs/research/ocr.md: 99% of words exactly right.

    uv run --directory backend python ../eval/ocr/measure.py [--work DIR] [--engines A,B]

Every engine's output (``out/<engine>/<page>.<condition>.txt``, as run.py writes it) against the
page's truth (``truth/<page>.txt``), per engine and condition (the strata), pooled over pages:

- ``words``: word accuracy regardless of reading order, 1 minus the bag-of-words error rate
  (OCR-D's definition): the larger of the truth's words missing from the output and the output's
  words missing from the truth, over the truth's words. A word read wrongly counts once. The
  measure for the target: a page parser that orders two columns differently is not wrong.
- ``ordered``: 1 minus the word error rate with the order kept (edits over the truth's words).
- ``ids``: share of the truth's identifiers found exactly ("2026/35", "15.03.2025", "E-83913885").
- ``tcs``: Turkish character sensitivity (OCRTurk): share of the truth's ç ğ ı ö ş ü and capitals
  the output keeps, by character alignment.
- ``invented``: share of the output's words in runs of three or more that the truth lacks: text
  the model wrote and the page does not hold. ``loops``: pages with a phrase of four or more
  words repeated three times that the truth does not repeat.
- ``lines``: share of the truth's lines with at least half their words in the output; a skipped
  line or block shows here.
- the worst decile of pages by ``words``, and the 95% interval of ``words`` from a bootstrap over
  pages (words on a page err together, so pages are resampled, not words).

Text is compared after Unicode NFC, plain apostrophes and dashes and words joined across line-end
hyphens, case kept: "İ" and "I" are different letters and Python's ``lower()`` would map "İ" to
"i" with a combining dot.
"""

import argparse
import json
import random
import re
import statistics
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz.distance import Levenshtein

HERE = Path(__file__).resolve().parent
TURKISH = frozenset("çğıöşüÇĞİÖŞÜ")
# Typographic quotes, the acute accent and dash variants written as plain ones (by code point,
# so the source holds none of them).
PLAIN = str.maketrans(
    dict.fromkeys(map(chr, (0x2018, 0x2019, 0x60, 0xB4)), "'")
    | dict.fromkeys(map(chr, (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2212)), "-")
)
_EDGE = "()[]{}<>\"'«»“”‘’.,;:!?*•"
MIN_ID_LENGTH = 4
RUN = 3  # words absent from the truth, in a row, that count as invented text
LOOP_WORDS, LOOP_TIMES = 4, 3
LINE_FOUND = 0.5
BOOTSTRAP = 2000


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFC", text).translate(PLAIN)
    return re.sub(r"-\n(?=\w)", "", text)


def words(text: str) -> list[str]:
    """The words of ``text``: a token with no letter or digit (a bullet, a dash, a table's
    pipe) is not one, in the truth or in an output."""
    found = (t.strip(_EDGE) for t in normalise(text).split())
    return [w for w in found if any(ch.isalnum() for ch in w)]


def is_identifier(word: str) -> bool:
    alnum = [ch for ch in word if ch.isalnum()]
    digits = sum(ch.isdigit() for ch in alnum)
    return len(word) >= MIN_ID_LENGTH and digits > 0 and digits * 2 >= len(alnum)


@dataclass
class Page:
    truth_words: int
    bag_errors: int
    ordered_errors: int
    ids: int
    ids_found: int
    turkish: int
    turkish_kept: int
    output_words: int
    invented: int
    loop: bool
    lines: int
    lines_found: int

    @property
    def accuracy(self) -> float:
        return 1 - self.bag_errors / self.truth_words if self.truth_words else 1.0


def page(truth_text: str, output_text: str) -> Page:
    truth, output = words(truth_text), words(output_text)
    t, o = Counter(truth), Counter(output)
    bag_errors = max(sum((t - o).values()), sum((o - t).values()))
    ids = [w for w in truth if is_identifier(w)]
    found = Counter(output)
    ids_found = sum(min(n, found[w]) for w, n in Counter(ids).items())
    turkish, kept = turkish_characters(normalise(truth_text), normalise(output_text))
    return Page(
        truth_words=len(truth),
        bag_errors=min(bag_errors, max(len(truth), len(output))),
        ordered_errors=Levenshtein.distance(truth, output),
        ids=len(ids),
        ids_found=ids_found,
        turkish=turkish,
        turkish_kept=kept,
        output_words=len(output),
        invented=invented(output, t),
        loop=looping(output) and not looping(truth),
        lines=sum(1 for line in truth_text.splitlines() if words(line)),
        lines_found=lines_found(truth_text, found),
    )


def turkish_characters(truth: str, output: str) -> tuple[int, int]:
    """The truth's Turkish letters, and how many the output keeps where alignment puts them."""
    lost = {
        position
        for operation, position, _ in Levenshtein.editops(truth, output)
        if operation in {"replace", "delete"} and truth[position] in TURKISH
    }
    total = sum(1 for ch in truth if ch in TURKISH)
    return total, total - len(lost)


def invented(output: list[str], truth: Counter[str]) -> int:
    """Words of the output in runs of RUN or more that the truth does not hold."""
    count = run = 0
    for word in output:
        if truth[word] == 0:
            run += 1
            continue
        count += run if run >= RUN else 0
        run = 0
    return count + (run if run >= RUN else 0)


def looping(text: list[str]) -> bool:
    grams = Counter(tuple(text[i : i + LOOP_WORDS]) for i in range(len(text) - LOOP_WORDS + 1))
    return any(n >= LOOP_TIMES for n in grams.values())


def lines_found(truth_text: str, output: Counter[str]) -> int:
    count = 0
    for line in truth_text.splitlines():
        line_words = words(line)
        if line_words and sum(1 for w in line_words if output[w]) >= LINE_FOUND * len(line_words):
            count += 1
    return count


def interval(pages: list[Page]) -> tuple[float, float]:
    """The 95% interval of pooled word accuracy, resampling pages."""
    pick = random.Random(7).choices  # noqa: S311  (a bootstrap, not a secret)
    values = []
    for _ in range(BOOTSTRAP):
        sample = pick(pages, k=len(pages))
        total = sum(p.truth_words for p in sample) or 1
        values.append(1 - sum(p.bag_errors for p in sample) / total)
    values.sort()
    return values[int(0.025 * BOOTSTRAP)], values[int(0.975 * BOOTSTRAP)]


def summary(pages: list[Page]) -> dict[str, float]:
    total = sum(p.truth_words for p in pages) or 1
    output = sum(p.output_words for p in pages) or 1
    worst = sorted(p.accuracy for p in pages)[: max(1, len(pages) // 10)]
    low, high = interval(pages)
    return {
        "pages": len(pages),
        "truth words": sum(p.truth_words for p in pages),
        "words": 1 - sum(p.bag_errors for p in pages) / total,
        "low": low,
        "high": high,
        "ordered": max(0.0, 1 - sum(p.ordered_errors for p in pages) / total),
        "ids": sum(p.ids_found for p in pages) / (sum(p.ids for p in pages) or 1),
        "tcs": sum(p.turkish_kept for p in pages) / (sum(p.turkish for p in pages) or 1),
        "invented": sum(p.invented for p in pages) / output,
        "loops": sum(p.loop for p in pages),
        "lines": sum(p.lines_found for p in pages) / (sum(p.lines for p in pages) or 1),
        "worst 10%": statistics.fmean(worst),
    }


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("--work", type=Path, default=HERE / "work")
    options.add_argument("--engines", help="comma-separated; all in out/ by default")
    options.add_argument("--json", type=Path, help="also write the table here")
    args = options.parse_args()
    out = args.work / "out"
    engines = args.engines.split(",") if args.engines else sorted(p.name for p in out.iterdir())
    truths = {p.stem: p.read_text(encoding="utf-8") for p in (args.work / "truth").glob("*.txt")}
    # Real scans have hand-verified transcriptions of their own (README.md).
    real = {p.stem: p.read_text(encoding="utf-8") for p in (HERE / "real").glob("*.txt")}
    results: dict[str, dict[str, dict[str, float]]] = {}
    for engine in engines:
        strata: dict[str, list[Page]] = {}
        for output in sorted((out / engine).glob("*.txt")):
            name, _, condition = output.stem.rpartition(".")
            truth = (real if condition == "real" else truths).get(name)
            if truth is not None:
                scored = page(truth, output.read_text(encoding="utf-8"))
                strata.setdefault(condition, []).append(scored)
        results[engine] = {c: summary(p) for c, p in sorted(strata.items())}
    columns = (
        "pages",
        "words",
        "low",
        "high",
        "ordered",
        "ids",
        "tcs",
        "invented",
        "loops",
        "lines",
        "worst 10%",
    )
    print(f"{'engine':30} {'stratum':8}" + "".join(f"{c:>10}" for c in columns))
    for engine, strata in results.items():
        for condition, row in strata.items():
            cells = "".join(
                f"{row[c]:>10.0f}" if c in {"pages", "loops"} else f"{row[c]:>10.4f}"
                for c in columns
            )
            print(f"{engine:30} {condition:8}{cells}")
    if args.json:
        args.json.write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
