"""Several readings of a page voted word by word (ROVER; ADR 0020, docs/benchmarks/ocr.md): the
product's form of eval/ocr/vote.py.

The first reading, the pivot, is the frame. Every other reading is aligned to it (edit operations
over word sequences), either as read or with its lines put in the pivot's order, whichever agrees
more with the pivot: engines read columns and boxes in different orders. At each of the pivot's
words the reading most voices give wins, ties going to the earlier voice; a place most voices
read nothing at (the pivot invented or repeated text) is left out, and a word most of the other
voices insert at the same place is added. Nothing new is written: every word is some voice's
reading, with at most the circumflexes of the voice trusted with them.

Words are compared as eval measures them: NFC, plain apostrophes and dashes, words joined across
line-end hyphens, punctuation stripped from their edges. The text keeps the pivot's lines and the
punctuation around its words: a voted word goes on its pivot word's line, an added word on the
line of the pivot word before it, and the pivot's tokens without a letter or digit (bullets,
dashes) stay where they are.

Eval's lexicon is not here: Turkish word frequencies (wordfreq, CC BY-SA data) added 0.15 points
of words on old books, the character language model in their place nothing.
"""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from rapidfuzz.distance import Levenshtein

PLAIN = str.maketrans(
    dict.fromkeys(map(chr, (0x2018, 0x2019, 0x60, 0xB4)), "'")
    | dict.fromkeys(map(chr, (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2212)), "-")
)
EDGE = "()[]{}<>\"'«»“”‘’.,;:!?*•"
# Letters Turkish has not, as recognisers trained on many Latin alphabets write the Turkish letter
# they look like: the Romanian s with a comma for ş, I with an acute for İ, a grave or acute i
# for î. Mapped before the vote; in eval +0.1 to +0.8 points of words.
FOREIGN = str.maketrans(
    {
        "ș": "ş",
        "Ș": "Ş",
        "š": "ş",
        "Š": "Ş",
        "č": "ç",
        "Č": "Ç",
        "ć": "ç",
        "Ć": "Ç",
        "ġ": "ğ",
        "Ġ": "Ğ",
        "ǧ": "ğ",
        "Ǧ": "Ğ",
        "Í": "İ",
        "Ì": "İ",
        "í": "î",
        "ì": "î",
        "ł": "l",
        "Ł": "L",
        "ę": "e",
        "ą": "a",
        "ā": "â",
        "á": "â",
        "à": "â",
        "ū": "û",
        "ú": "û",
        "ù": "û",
    }
)
FOLD = str.maketrans("çğıöşüâîûÇĞİÖŞÜÂÎÛ", "cgiosuaiuCGIOSUAIU")
HATS = frozenset("âîûÂÎÛ")
# A word pair or triple seen this many times in the pivot at most places a line (in_order_of).
RARE = 3
# A voice reading fewer words than this share of the page's median reading failed on that page
# (an empty table, a crop it could not read) and is left out rather than voting "nothing here".
SHORT = 0.3


@dataclass(frozen=True)
class Token:
    raw: str  # as read, with the punctuation at its edges
    key: str  # what is compared: the edge punctuation stripped
    line: int

    @property
    def word(self) -> bool:
        return any(ch.isalnum() for ch in self.key)


def tokens(text: str) -> list[Token]:
    """A reading's tokens with their lines, words joined across line-end hyphens."""
    text = unicodedata.normalize("NFC", text).translate(PLAIN).translate(FOREIGN)
    text = re.sub(r"-\n(?=\w)", "", text)
    return [
        Token(raw, raw.strip(EDGE), number)
        for number, line in enumerate(text.splitlines())
        for raw in line.split()
    ]


def words(text: str) -> list[Token]:
    return [t for t in tokens(text) if t.word]


def folded(word: str) -> str:
    return word.translate(FOLD)


def aligned(pivot: list[str], other: list[str]) -> tuple[list[int | None], list[list[int]]]:
    """For each of the pivot's words, the index of the other's word at that place (None where it
    has none), and the indices of the words the other inserts before each place (one list more,
    for the end)."""
    at: list[int | None] = [None] * len(pivot)
    inserted: list[list[int]] = [[] for _ in range(len(pivot) + 1)]
    for op in Levenshtein.opcodes(pivot, other):
        tag, i1, i2, j1, j2 = op.tag, op.src_start, op.src_end, op.dest_start, op.dest_end
        if tag in {"equal", "replace"}:
            for k in range(i2 - i1):
                if j1 + k < j2:
                    at[i1 + k] = j1 + k
            if tag == "replace" and (j2 - j1) > (i2 - i1):
                inserted[i2].extend(range(j1 + (i2 - i1), j2))
        elif tag == "insert":
            inserted[i1].extend(range(j1, j2))
    return at, inserted


def with_hats(word: str, marked: str) -> str:
    """``word`` with the circumflexes ``marked`` (the same word, read by another voice) puts on
    its letters: "mali" and "malî" give "malî"."""
    if len(word) != len(marked) or folded(word) != folded(marked):
        return word
    return "".join(m if m in HATS else w for w, m in zip(word, marked, strict=True))


def chosen(readings: list[str], marked: str | None) -> str:
    """The reading most voices give, the earliest of those tied, with the circumflexes of
    ``marked``, the reading of the voice trusted with them."""
    counts = Counter(readings)
    best = max(counts.values())
    pick = next(r for r in readings if counts[r] == best)
    return pick if marked is None else with_hats(pick, marked)


def in_order_of(pivot: list[str], chunks: list[list[Token]]) -> list[Token]:
    """Another voice's lines put in the pivot's reading order: each goes where its word pairs and
    triples that are rare in the pivot (three times at most) say it stands; a line with none
    follows the one before it."""
    index: dict[tuple[str, ...], list[int]] = {}
    for n in (3, 2):
        for k in range(len(pivot) - n + 1):
            index.setdefault(tuple(pivot[k : k + n]), []).append(k)
    rare = {gram: places for gram, places in index.items() if len(places) <= RARE}
    placed: list[tuple[float, int, list[Token]]] = []
    previous = -1.0
    for number, chunk in enumerate(chunks):
        keys = [t.key for t in chunk]
        offsets: Counter[int] = Counter()
        for n in (3, 2):
            for k in range(len(keys) - n + 1):
                for place in rare.get(tuple(keys[k : k + n]), ()):
                    offsets[place - k] += 1
            if offsets:
                break
        where = float(offsets.most_common(1)[0][0]) if offsets else previous + 0.001
        placed.append((where, number, chunk))
        previous = where
    return [t for _, _, chunk in sorted(placed, key=lambda p: (p[0], p[1])) for t in chunk]


def agreement(pivot: list[str], others: list[list[str]]) -> float:
    """How often the other voices, aligned to the pivot, read the pivot's own word: an alignment
    that pairs the right words agrees more, and no truth is needed to see it."""
    if not pivot or not others:
        return 0.0
    same = sum(
        1
        for other in others
        for i, j in enumerate(aligned(pivot, other)[0])
        if j is not None and other[j] == pivot[i]
    )
    return same / (len(pivot) * len(others))


def present(lengths: list[int]) -> list[int]:
    """The voices (indices) whose reading of the page is long enough to vote; the pivot always."""
    median = sorted(lengths)[len(lengths) // 2]
    return [k for k, n in enumerate(lengths) if k == 0 or n >= SHORT * median]


def _lines(text: str) -> list[list[Token]]:
    found: dict[int, list[Token]] = {}
    for t in words(text):
        found.setdefault(t.line, []).append(t)
    return list(found.values())


def _dressed(token: Token, key: str) -> str:
    """``key`` with the punctuation around ``token``'s word."""
    if key == token.key:
        return token.raw
    lead = len(token.raw) - len(token.raw.lstrip(EDGE))
    trail = len(token.raw.rstrip(EDGE))
    return token.raw[:lead] + key + token.raw[trail:]


def vote(readings: list[str], hats: int | None = None) -> str:
    """The voted text of a page's readings, the pivot's first. ``hats`` is the index of the
    voice whose circumflexes go on the chosen words ("malî"), which most voices drop."""
    pivot_tokens = tokens(readings[0])
    pivot = [t for t in pivot_tokens if t.word]
    keys = [t.key for t in pivot]
    as_read = [words(text) for text in readings[1:]]
    reordered = [in_order_of(keys, _lines(text)) for text in readings[1:]]
    if agreement(keys, [[t.key for t in r] for r in reordered]) > agreement(
        keys, [[t.key for t in r] for r in as_read]
    ):
        as_read = reordered
    voices = [pivot, *as_read]
    kept = present([len(v) for v in voices])
    hats = kept.index(hats) if hats is not None and hats in kept else None
    voices = [voices[k] for k in kept]
    others = voices[1:]
    alignments = [aligned(keys, [t.key for t in other]) for other in others]
    majority = len(voices) // 2 + 1

    picks: list[str | None] = []
    added: list[list[Token]] = []
    for i in range(len(pivot) + 1):
        counts: Counter[str] = Counter()
        first: dict[str, Token] = {}
        for (_, inserted), other in zip(alignments, others, strict=True):
            for key in dict.fromkeys(other[j].key for j in inserted[i]):
                counts[key] += 1
                first.setdefault(key, other[next(j for j in inserted[i] if other[j].key == key)])
        added.append([first[key] for key, n in counts.items() if n >= majority])
        if i == len(pivot):
            break
        slot: list[str | None] = [keys[i]]
        for (at, _), other in zip(alignments, others, strict=True):
            j = at[i]
            slot.append(None if j is None else other[j].key)
        here = [key for key in slot if key is not None]
        # Reading nothing here is a vote too: a word most voices did not read is left out.
        if len(voices) - len(here) >= majority:
            picks.append(None)
            continue
        picks.append(chosen(here, None if hats is None else slot[hats]))

    lines: dict[int, list[str]] = {}
    i = 0
    previous_line = pivot[0].line if pivot else 0
    for token in pivot_tokens:
        if not token.word:
            lines.setdefault(token.line, []).append(token.raw)
            continue
        lines.setdefault(previous_line, []).extend(t.raw for t in added[i])
        pick = picks[i]
        if pick is not None:
            lines.setdefault(token.line, []).append(_dressed(token, pick))
        previous_line = token.line
        i += 1
    lines.setdefault(previous_line, []).extend(t.raw for t in added[len(pivot)])
    return "\n".join(" ".join(line) for _, line in sorted(lines.items()) if line)
