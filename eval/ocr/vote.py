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
from collections.abc import Callable
from pathlib import Path

from rapidfuzz.distance import Levenshtein

sys.path.insert(0, str(Path(__file__).resolve().parent))

from measure import words

# Zipf frequencies (wordfreq): below UNKNOWN a reading is not taken for a Turkish word, from
# KNOWN on it is one.
UNKNOWN, KNOWN = 1.5, 2.5
# With the rule ``gap``, a variant in Turkish letters replaces the chosen reading when it is this
# much more common (zipf, so 1.5 is about thirty times): "egitim" 3.6 gives way to "eğitim" 5.6,
# "diş" 4.7 stays beside "dış" 5.3.
GAP = 1.5
# A prefix this long at least stands for an inflected word the lexicon lacks ("fıkrada": "fıkra").
STEM = 4
# A word pair or triple seen this many times in the pivot at most places a chunk (in_order_of).
RARE = 3
FOLD = str.maketrans("çğıöşüâîûÇĞİÖŞÜÂÎÛ", "cgiosuaiuCGIOSUAIU")
HATS = set("âîûÂÎÛ")


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


def with_hats(word: str, marked: str) -> str:
    """``word`` with the circumflexes ``marked`` (the same word, read by another engine) puts
    on its letters: "mali" and "malî" give "malî"."""
    if len(word) != len(marked) or folded(word) != folded(marked):
        return word
    return "".join(m if m in HATS else w for w, m in zip(word, marked, strict=True))


def commoner(a: str, b: str, frequency: dict[str, float]) -> float:
    """How much more common ``a`` is than ``b``, two variants in Turkish letters (zipf). An
    inflected form the lexicon lacks is judged by its longest known prefix that still holds the
    letters the two differ in: "fıkrada" by "fıkra"."""
    differ = next((k for k, (x, y) in enumerate(zip(a, b, strict=False)) if x != y), len(a))
    for k in range(len(a), max(differ + 1, STEM) - 1, -1):
        fa, fb = frequency.get(a[:k], 0.0), frequency.get(b[:k], 0.0)
        if fa or fb:
            return fa - fb
    return 0.0


def choose(
    readings: list[str],
    frequency: dict[str, float] | None,
    rule: str = "unknown",
    letters: str | None = None,
    hats: str | None = None,
) -> str:
    """The reading most engines give. Where the readings differ only in Turkish letters,
    ``letters`` (the reading of the engine trusted with them) settles which, and ``hats`` (that
    of the engine trusted with circumflexes, which most engines drop) adds its circumflexes.
    With a lexicon and
    the rule ``first``, variants in
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
    if letters is not None and folded(letters) == folded(pick):
        pick = letters
    if hats is not None:
        pick = with_hats(pick, hats)
    if frequency is not None and rule == "gap":
        variants = {r for r in readings if r != pick and folded(r) == folded(pick)}
        better = [r for r in variants if commoner(r, pick, frequency) >= GAP]
        if better:
            pick = max(better, key=lambda r: commoner(r, pick, frequency))
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
    readings: list[list[str]],
    frequency: dict[str, float] | None = None,
    rule: str = "unknown",
    letters: int | None = None,
    hats: int | None = None,
    settle: Callable[[int, list[str], str], str] | None = None,
) -> list[str]:
    """``letters`` is the index of the engine whose Turkish letters are trusted over the
    majority's: vision-language models drop them alike ("fıkra" read "fikra" by two of them)
    and would outvote the one engine that reads them. ``hats`` is the index of the engine
    whose circumflexes are added ("malî"). ``settle``, given a place where the engines disagree
    (the pivot's word index, the readings, the vote's pick), may decide it otherwise: by the
    image, for one."""
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
        slot = [pivot[i], *(at[i] for at, _ in alignments)]
        trusted = None if letters is None else slot[letters]
        marked = None if hats is None else slot[hats]
        pick = choose(here, frequency, rule, trusted, marked)
        if settle is not None and len(set(here)) > 1:
            pick = settle(i, here, pick)
        result.append(pick)
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

    # with the prefixes commoner() looks up
    keys = {w[:k] for w in vocabulary for k in range(STEM, len(w) + 1)}
    return {w: zipf_frequency(w, "tr") for w in keys}


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("--work", type=Path, required=True)
    options.add_argument("--engines", required=True)
    options.add_argument("--name")
    options.add_argument("--lexicon", action="store_true")
    options.add_argument("--rule", choices=("unknown", "first", "gap"), default="unknown")
    # The engine whose Turkish letters settle readings that differ only in them.
    options.add_argument("--letters")
    # The engine whose circumflexes are added to the chosen reading.
    options.add_argument("--hats")
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
        letters = engines.index(args.letters) if args.letters else None
        hats = engines.index(args.hats) if args.hats else None
        result = vote(page_readings, frequency, args.rule, letters, hats)
        (target / page).write_text(" ".join(result), encoding="utf-8")
    print(name, len(pages), "pages")


if __name__ == "__main__":
    main()
