"""Whose words a number is: an answer that reports what a person said must not give that person
a number the source gives someone else.

A small model joins two witnesses summed up in one paragraph: asked what one said, it adds the
other's words ("Aydın Kocabey ... cumartesi 13:00'te çıkıldığını belirtmiştir", where 13:00 is
the other witness's). Verification (verification.py) finds 13:00 in the source and is satisfied.
This check reads the source as reported speech: a person's words run from where the source names
them to where it names the next person who says something. A sentence of the answer that says a
person said something (a verb of saying and a name the cited source holds) and states a number
is misattributed when every place that number stands in the cited sources is in someone else's
words. A number before anyone speaks, or a source without people speaking, decides nothing.

People are found by their names: two or three words with capitals ("Aydın Kocabey", "EROL
TUNÇBİLEK" in an OCR'd minute), roles, places, days and months left out. In a source a name is
a speaker when a verb of saying follows it closely ("..." demiş, beyan etti). Only numbers are
checked, and two words in a row: "yarım gün" that stands only in the other witness's words,
in a sentence none of whose numbers or pairs of words stands in the person's own, is
misattributed too.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from synapse.chat.verification import (
    Checked,
    claims,
    fold,
    sentences,
    stands_in,
    strip_unsupported,
)

# Saying, in the past forms Turkish reports words with: dedi, demiş, söylemiştir, beyan etti,
# ifade etmiştir, belirtti, anlatmış. Read on folded text.
_SAYS = re.compile(
    r"(?<!\w)(?:dedi\w*|demiş\w*|söyle(?:di|miş)\w*|beyan et\w*|ifade et(?:ti|miş)\w*"
    r"|belirt(?:ti|miş)\w*|anlat(?:tı|mış)\w*)"
)
# How far after a name its verb of saying may come: past the quoted words of a short statement.
SAYS_WITHIN = 200
_WORD = re.compile(r"[^\W\d_]+")
# Words with capitals that are not names: roles, courts and offices, days and months.
_NOT_NAMES = frozenset(
    {
        "davacı", "davalı", "tanığı", "tanık", "tanıklar", "vekili", "av", "avukat", "sayın",
        "mahkemesi", "mahkeme", "hakim", "hâkim", "katip", "kâtip", "bilirkişi", "heyet",
        "heyeti", "raporu", "rapor", "kanunu", "kanun", "maddesi", "esas", "karar", "dosya",
        "tutanak", "tutanağı", "celse", "hukuk", "asliye", "ticaret", "sulh", "aile", "icra",
        "dairesi", "noterliği", "noter", "belediyesi", "belediye", "başkanı", "başkanlığı",
        "müdürlüğü", "bakanlığı", "kurulu", "kurumu", "anonim", "şirketi", "limited", "sanayi",
        "türkiye", "cumhuriyeti", "tc", "pazartesi", "salı", "çarşamba", "perşembe", "cuma",
        "cumartesi", "pazar", "ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz",
        "ağustos", "eylül", "ekim", "kasım", "aralık", "gereği", "düşünüldü", "açıklamalar",
        "konu", "sonuç", "istem", "talep", "cevap", "dilekçe", "dilekçesi", "kimlik", "no",
    }
)  # fmt: skip


# Words that say nothing of whose words a sentence holds: joining words and the verbs of saying.
_PLAIN = frozenset(
    {
        "ve", "ile", "da", "de", "bir", "bu", "şu", "için", "gibi", "olarak",
        "olduğunu", "olduğu", "ise", "veya", "çok", "daha", "her", "kadar", "tanığı",
        "tanık", "davacı", "davalı", "beyan", "etmiştir", "etti", "ifade", "belirtmiştir",
        "belirtti", "söylemiştir", "söyledi", "demiştir", "dedi", "anlatmıştır",
    }
)  # fmt: skip


@dataclass(frozen=True)
class Misattributed:
    """A sentence of the answer that gives ``person`` numbers or words someone else said."""

    sentence: str
    person: str
    claims: tuple[str, ...]


def names(text: str) -> list[str]:
    """The people ``text`` names, folded, each once, in order."""
    found: dict[str, None] = {}
    run: list[str] = []
    last_end = -1

    def close() -> None:
        if 2 <= len(run) <= 3:  # noqa: PLR2004  (a first name and one or two surnames)
            found.setdefault(fold(" ".join(run)), None)
        run.clear()

    for match in _WORD.finditer(text):
        word = match.group()
        capital = len(word) > 1 and word[0].isupper() and (word[1:].islower() or word.isupper())
        adjacent = last_end >= 0 and not text[last_end : match.start()].strip()
        if not capital or fold(word) in _NOT_NAMES or not adjacent:
            close()
        if capital and fold(word) not in _NOT_NAMES:
            run.append(word)
        last_end = match.end()
    close()
    return list(found)


def _at(name: str, folded: str) -> list[int]:
    return [m.start() for m in re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", folded)]


def _speakers(source: str, folded: str, person: str) -> list[tuple[int, str]]:
    """Where each person who says something in ``source`` is named, in order: ``person`` and
    every name a verb of saying follows closely."""
    speaking = {person} | {
        name
        for name in names(source)
        if any(_SAYS.search(folded, at, at + SAYS_WITHIN) for at in _at(name, folded))
    }
    return sorted((at, name) for name in speaking for at in _at(name, folded))


def _owners(claim: str, source: str, person: str) -> set[str | None]:
    """Whose words each place ``claim`` stands in ``source`` is (None: before anyone speaks)."""
    folded = fold(source)
    mentions = _speakers(source, folded, person)
    owners: set[str | None] = set()
    for at in _at(claim, folded):
        before = [name for position, name in mentions if position < at]
        owners.add(before[-1] if before else None)
    return owners


def _stem(word: str) -> str:
    """A word's first letters, enough to find it under another suffix."""
    return word[: max(3, len(word) - 3)]


def _pairs(sentence: str, person: str) -> list[tuple[str, str]]:
    """Two words of ``sentence`` in a row, its person's name and plain words left out."""
    words = [
        w
        for w in _WORD.findall(fold(sentence))
        if len(w) > 2 and w not in _PLAIN and w not in person.split()  # noqa: PLR2004
    ]
    return list(pairwise(words))


def _holds(pair: tuple[str, str], text: str) -> bool:
    first, second = (re.escape(_stem(word)) for word in pair)
    return re.search(rf"(?<!\w){first}\w*\s+{second}\w*", text) is not None


def _said_by(source: str, person: str) -> dict[str | None, str]:
    """``source`` by who says it: each person's words run from where it names them to where it
    names the next person who says something (None: before anyone speaks)."""
    folded = fold(source)
    mentions = _speakers(source, folded, person)
    parts: dict[str | None, list[str]] = {None: [folded[: mentions[0][0]] if mentions else folded]}
    ends = [at for at, _ in mentions[1:]] + [len(folded)]
    for (at, name), end in zip(mentions, ends, strict=True):
        parts.setdefault(name, []).append(folded[at:end])
    return {owner: " ".join(texts) for owner, texts in parts.items()}


def _words_of_another(sentence: str, holding: Sequence[str], person: str) -> tuple[str, ...]:
    """The pairs of words ``sentence`` gives ``person`` that stand only in someone else's words,
    when nothing of the sentence (a pair, a number) stands in the person's own."""
    said = [_said_by(source, person) for source in holding]
    own = " ".join(parts.get(person, "") for parts in said)
    others = " ".join(
        text for parts in said for owner, text in parts.items() if owner not in {person, None}
    )
    pairs = _pairs(sentence, person)
    if any(_holds(pair, own) for pair in pairs) or any(stands_in(c, own) for c in claims(sentence)):
        return ()
    return tuple(" ".join(pair) for pair in pairs if _holds(pair, others))


def misattributed(
    sentences: Sequence[str], sources: Sequence[str], citations: Sequence[int]
) -> tuple[Misattributed, ...]:
    """The sentences that put numbers or words in the mouth of someone the cited sources do not
    give them to. ``sources`` are numbered from 1; ``citations`` are the numbers the answer
    cites."""
    cited_sources = [sources[n - 1] for n in citations if 1 <= n <= len(sources)]
    wrong = []
    for sentence in sentences:
        folded_sentence = fold(sentence)
        if not _SAYS.search(folded_sentence):
            continue
        for person in names(sentence):
            holding = [s for s in cited_sources if _at(person, fold(s))]
            if not holding:
                continue
            given = []
            for claim in claims(sentence):
                owners = set().union(*(_owners(claim, s, person) for s in holding))
                if owners and person not in owners and None not in owners:
                    given.append(claim)
            if not given:
                given = list(_words_of_another(sentence, holding, person))
            if given:
                wrong.append(Misattributed(sentence, person, tuple(given)))
                break
    return tuple(wrong)


def without_wrong(
    text: str, checked: Checked, wrong: Sequence[Misattributed]
) -> tuple[str, tuple[str, ...]]:
    """``text`` without the sentences verification found wrong, and those sentences."""
    if checked.ok and not wrong:
        return text, ()
    text, removed = strip_unsupported(text, checked.unsupported)
    gone = {w.sentence for w in wrong}
    kept = [s for s in sentences(text) if s not in gone]
    return " ".join(kept), (*removed, *(s for s in sentences(text) if s in gone))
