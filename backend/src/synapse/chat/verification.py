"""Answer verification (ADR 0010, query rule 10): every number and identifier an answer states
must be in the sources it cites.

A claim is a token of the answer with a digit in it: an amount, a date, a decision or law number,
an article, a code ("2023/1497", "22.12.2023", "e-91810702", "302250000"). Both sides are
compared folded: Turkish lower case, plain apostrophes and dashes, thousands separators dropped
and number words written as digits (numerals.py), so "302.250.000 TL" supports "302250000 TL"
and "üç yıl" supports "3 yıl". A claim is supported when it stands in a cited source as a whole
token: "2023" stands in "22.12.2023", "1497" in "2023/1497", but not in "14970". An identifier
written differently ("e91810702" for "e-91810702") is not supported: changing an identifier is
the error this check exists for.

The answer cites its sources inline, ``[n]`` or ``[n, m]`` after the statement they support
(answering.py). ``check`` sorts the claims into supported, supported only by a source the answer
shows but does not cite (``uncited``: grounded, cited wrongly) and not in any source shown
(``unsupported``: what the model made up or changed).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from synapse.chat.numerals import numeric
from synapse.knowledge.public import lower

PLAIN = str.maketrans(
    {chr(c): "'" for c in (0x2018, 0x2019, 0x02BC)}
    | {chr(c): '"' for c in (0x201C, 0x201D)}
    | {chr(c): "-" for c in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2212)}
)
CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_CLAIM = re.compile(r"[\w./,-]*\d[\w./,-]*")
_EDGES = ".,/-_"
# A sentence ends at ., ! or ? followed by white space, unless the dot ends a number ("18.
# madde") or a common abbreviation: ordinals and abbreviations are everywhere in Turkish
# official writing.
_ABBREVIATIONS = frozenset(
    {"md", "mad", "no", "s", "sy", "vb", "vs", "bkz", "dr", "prof", "doç", "av", "sn", "t.c", "tc"}
)


@dataclass(frozen=True)
class Checked:
    claims: tuple[str, ...]
    uncited: tuple[str, ...]
    unsupported: tuple[str, ...]
    # For each uncited claim, the first source shown that holds it: the citation it lacks.
    lacking: tuple[int, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.unsupported


def fold(text: str) -> str:
    return numeric(" ".join(lower(text).translate(PLAIN).split()))


def claims(text: str) -> list[str]:
    """The numbers and identifiers ``text`` states, folded, each once, in order."""
    found: dict[str, None] = {}
    for token in _CLAIM.findall(fold(CITATION.sub(" ", text))):
        claim = token.strip(_EDGES)
        if any(ch.isdigit() for ch in claim):
            found.setdefault(claim, None)
    return list(found)


def stands_in(claim: str, folded_source: str) -> bool:
    return re.search(rf"(?<![\w]){re.escape(claim)}(?![\w])", folded_source) is not None


def cited(text: str) -> list[int]:
    """The source numbers ``text`` cites, each once, in order."""
    numbers: dict[int, None] = {}
    for group in CITATION.findall(text):
        for number in group.split(","):
            numbers.setdefault(int(number), None)
    return list(numbers)


def check(answer: str, sources: Sequence[str], citations: Sequence[int]) -> Checked:
    """``answer``'s claims against ``sources`` (numbered from 1); ``citations`` are the numbers
    it cites."""
    folded = [fold(source) for source in sources]
    in_cited = [folded[n - 1] for n in citations if 1 <= n <= len(folded)]
    found = claims(answer)
    uncited, unsupported, lacking = [], [], []
    for claim in found:
        if any(stands_in(claim, source) for source in in_cited):
            continue
        holding = [n for n, source in enumerate(folded, start=1) if stands_in(claim, source)]
        if holding:
            uncited.append(claim)
            lacking.append(holding[0])
        else:
            unsupported.append(claim)
    return Checked(tuple(found), tuple(uncited), tuple(unsupported), tuple(dict.fromkeys(lacking)))


def sentences(text: str) -> list[str]:
    """``text`` split into sentences, each with its trailing citation markers."""
    parts: list[str] = []
    start = 0
    for match in re.finditer(r"[.!?](?:\s*\[[\d,\s]+\])*(?=\s+)", text):
        end = match.end()
        before = text[start : match.start()].rstrip()
        word = re.split(r"\s", before)[-1] if before else ""
        if match.group().startswith(".") and (word[-1:].isdigit() or lower(word) in _ABBREVIATIONS):
            continue
        parts.append(text[start:end].strip())
        start = end
    if text[start:].strip():
        parts.append(text[start:].strip())
    return parts


def strip_unsupported(answer: str, unsupported: Sequence[str]) -> tuple[str, tuple[str, ...]]:
    """``answer`` without the sentences that state an unsupported claim, and those sentences."""
    bad = set(unsupported)
    kept: list[str] = []
    removed: list[str] = []
    for sentence in sentences(answer):
        (removed if bad.intersection(claims(sentence)) else kept).append(sentence)
    return " ".join(kept), tuple(removed)
