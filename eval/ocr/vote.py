"""Several engines' readings of a page, aligned word by word and voted (ROVER; docs/research).

    python eval/ocr/vote.py --work DIR --engines PIVOT,A,B [--name NAME] [--lexicon]

The pivot's words are the frame: every other engine is aligned to it (edit operations over
word sequences), and each of the pivot's words becomes the reading most engines give at that
place, ties going to the earlier engine in ``--engines``; where most engines read nothing
(the pivot looped or invented text), the pivot's word is left out. A word the pivot lacks is
added where most of the other engines insert that same word at that place. Nothing new is ever
written: every word of the result is some engine's reading.

Engines read columns and boxes in different orders. For each page the others are aligned
either as read or with their lines put in the pivot's order (in_order_of), whichever agrees
more with the pivot: reordering alone mends pages read in another order and breaks others.

With ``--lexicon``, readings that differ only in Turkish letters or circumflexes ("fıkra" and
"fikra") are looked up in Turkish word frequencies (wordfreq): by default the vote's winner gives
way to such a variant only when it is no Turkish word and the variant is (``--rule unknown``);
``--rule first`` settles every such group by frequency before the vote.

Writes ``out/<name>/<page>.<condition>.txt`` for every page all the engines read, for measure.py.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

from rapidfuzz.distance import Levenshtein

sys.path.insert(0, str(Path(__file__).resolve().parent))

from measure import words

# Zipf frequencies (wordfreq): below UNKNOWN a reading is not taken for a Turkish word, from
# KNOWN on it is one.
UNKNOWN, KNOWN = 1.5, 2.5
# A word pair or triple seen this many times in the pivot at most places a chunk (in_order_of).
RARE = 3
FOLD = str.maketrans("çğıöşüâîûÇĞİÖŞÜÂÎÛ", "cgiosuaiuCGIOSUAIU")


def folded(word: str) -> str:
    return word.translate(FOLD)


def aligned(pivot: list[str], other: list[str]) -> tuple[list[str | None], list[list[str]]]:
    """For each of the pivot's words, the other's word at that place (None where it has none),
    and the words the other inserts before each place (one more list, for the end)."""
    at: list[str | None] = [None] * len(pivot)
    inserted: list[list[str]] = [[] for _ in range(len(pivot) + 1)]
    for tag, i1, i2, j1, j2 in Levenshtein.opcodes(pivot, other):
        if tag in {"equal", "replace"}:
            for k in range(i2 - i1):
                if j1 + k < j2:
                    at[i1 + k] = other[j1 + k]
            if tag == "replace" and (j2 - j1) > (i2 - i1):
                inserted[i2].extend(other[j1 + (i2 - i1) : j2])
        elif tag == "insert":
            inserted[i1].extend(other[j1:j2])
    return at, inserted


def choose(readings: list[str], frequency: dict[str, float] | None, rule: str = "unknown") -> str:
    """The reading most engines give. With a lexicon and the rule ``first``, variants in
    Turkish letters go to the most common one before the vote; with ``unknown``, only when the
    winner is not a Turkish word ("fikra") and a variant read by some engine is ("fıkra"), so a
    rare word the page holds ("diş", not "dış") is kept."""
    if frequency is not None and rule == "first":
        groups: dict[str, list[str]] = {}
        for reading in readings:
            groups.setdefault(folded(reading), []).append(reading)
        readings = [
            max(group, key=lambda w: (frequency.get(w, 0.0), -group.index(w)))
            if len(set(group)) > 1
            else group[0]
            for group in (groups[folded(r)] for r in readings)
        ]
    counts = Counter(readings)
    best = max(counts.values())
    pick = next(r for r in readings if counts[r] == best)
    if frequency is not None and rule == "unknown" and frequency.get(pick, 0.0) < UNKNOWN:
        known = [
            r
            for r in readings
            if r != pick and folded(r) == folded(pick) and frequency.get(r, 0.0) >= KNOWN
        ]
        if known:
            pick = max(known, key=lambda w: frequency.get(w, 0.0))
    return pick


def vote(
    readings: list[list[str]], frequency: dict[str, float] | None = None, rule: str = "unknown"
) -> list[str]:
    pivot, others = readings[0], readings[1:]
    alignments = [aligned(pivot, other) for other in others]
    result: list[str] = []
    majority = len(readings) // 2 + 1
    for i in range(len(pivot) + 1):
        gap = Counter(w for _, inserted in alignments for w in set(inserted[i]))
        result.extend(w for w, n in gap.items() if n >= majority)
        if i == len(pivot):
            break
        here = [pivot[i]] + [at[i] for at, _ in alignments if at[i] is not None]
        # Reading nothing here is a vote too: a word most engines did not read (a pivot's
        # repetition loop, text it invented) is left out.
        if len(readings) - len(here) >= majority:
            continue
        result.append(choose(here, frequency, rule))
    return result


def in_order_of(pivot: list[str], chunks: list[list[str]]) -> list[str]:
    """Another engine's lines or paragraphs put in the pivot's reading order before the words
    are aligned: each goes where its word pairs and triples that are rare in the pivot (three
    times at most) say it stands there; a chunk with none follows the one before it. Two engines
    that read a page's columns or boxes in different orders then align instead of clashing."""
    index: dict[tuple[str, ...], list[int]] = {}
    for n in (3, 2):
        for k in range(len(pivot) - n + 1):
            index.setdefault(tuple(pivot[k : k + n]), []).append(k)
    rare = {gram: places for gram, places in index.items() if len(places) <= RARE}
    placed: list[tuple[float, int, list[str]]] = []
    previous = -1.0
    for number, chunk in enumerate(chunks):
        offsets: Counter[int] = Counter()
        for n in (3, 2):
            for k in range(len(chunk) - n + 1):
                for place in rare.get(tuple(chunk[k : k + n]), ()):
                    offsets[place - k] += 1
            if offsets:
                break
        where = float(offsets.most_common(1)[0][0]) if offsets else previous + 0.001
        placed.append((where, number, chunk))
        previous = where
    return [word for _, _, chunk in sorted(placed) for word in chunk]


def agreement(pivot: list[str], others: list[list[str]]) -> float:
    """How often the other engines, aligned to the pivot, read the pivot's own word: an
    alignment that pairs the right words agrees more, and the truth is not needed to see it."""
    if not pivot or not others:
        return 0.0
    same = sum(
        1 for other in others for i, w in enumerate(aligned(pivot, other)[0]) if w == pivot[i]
    )
    return same / (len(pivot) * len(others))


def lexicon(vocabulary: set[str]) -> dict[str, float]:
    from wordfreq import zipf_frequency  # noqa: PLC0415  (only for --lexicon)

    return {w: zipf_frequency(w, "tr") for w in vocabulary}


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("--work", type=Path, required=True)
    options.add_argument("--engines", required=True)
    options.add_argument("--name")
    options.add_argument("--lexicon", action="store_true")
    options.add_argument("--rule", choices=("unknown", "first"), default="unknown")
    # How the others are aligned: the page as one sequence, its chunks in the pivot's order, or
    # per page whichever of the two agrees more with the pivot (the default).
    options.add_argument("--order", choices=("page", "chunks", "best"), default="best")
    args = options.parse_args()
    engines = args.engines.split(",")
    name = args.name or "vote-" + "+".join(engines) + ("-lexicon" if args.lexicon else "")
    out = args.work / "out"
    target = out / name
    target.mkdir(parents=True, exist_ok=True)
    pages = sorted(p.name for p in (out / engines[0]).glob("*.txt"))
    pages = [p for p in pages if all((out / e / p).exists() for e in engines)]
    readings = {}
    for page in pages:
        texts = [(out / e / page).read_text(encoding="utf-8") for e in engines]
        pivot = words(texts[0])
        as_read = [words(text) for text in texts[1:]]
        reordered = [
            in_order_of(pivot, [w for line in text.splitlines() if (w := words(line))])
            for text in texts[1:]
        ]
        if args.order == "page":
            others = as_read
        elif args.order == "chunks":
            others = reordered
        else:
            better = agreement(pivot, reordered) > agreement(pivot, as_read)
            others = reordered if better else as_read
        readings[page] = [pivot, *others]
    frequency = None
    if args.lexicon:
        frequency = lexicon({w for page in readings.values() for r in page for w in r})
    for page, page_readings in readings.items():
        result = vote(page_readings, frequency, args.rule)
        (target / page).write_text(" ".join(result), encoding="utf-8")
    print(name, len(pages), "pages")


if __name__ == "__main__":
    main()
