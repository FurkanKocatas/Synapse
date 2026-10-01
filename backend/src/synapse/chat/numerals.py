"""Numbers written as numbers, so an answer and its sources can be compared (verification.py).

An answer often writes a number differently from its source: "3 yıl" for "üç yıl", "12 gün"
for "oniki gün", "302250000 TL" for "302.250.000 TL". ``numeric`` rewrites lower-cased text so
both sides agree: thousands separators between digits go, and a run of Turkish number words,
apart ("dokuz yüz yirmi bin") or joined ("oniki", "onbeş"), becomes its digits. Ordinals and
words with suffixes ("üçüncü", "ikisi") stay as they are. It is applied to both sides, so a word
that only looks like a number ("bir" as "a") changes both alike. The same rules as the answer
benchmark's scorer (eval/answers/numerals.py), which measured them on the golden set.
"""

import re
import string

UNITS = {
    "bir": 1,
    "iki": 2,
    "üç": 3,
    "dört": 4,
    "beş": 5,
    "altı": 6,
    "yedi": 7,
    "sekiz": 8,
    "dokuz": 9,
    "on": 10,
    "yirmi": 20,
    "otuz": 30,
    "kırk": 40,
    "elli": 50,
    "altmış": 60,
    "yetmiş": 70,
    "seksen": 80,
    "doksan": 90,
}
HUNDRED = 100
SCALES = {"bin": 1_000, "milyon": 1_000_000, "milyar": 1_000_000_000}
WORDS = UNITS | {"yüz": HUNDRED} | SCALES
# Longest first, so "altmış" is not read as "altı" and a rest.
MORPHEMES = sorted(WORDS, key=len, reverse=True)
# A dot or comma between digits followed by exactly three digits: a thousands separator
# ("302.250.000", "1.212"), not a decimal ("99,5") or a date ("22.12.2023").
THOUSANDS = re.compile(r"(?<=\d)[.,](?=\d{3}(?!\d))")
PUNCTUATION = string.punctuation + "‘’“”"


def split(word: str) -> list[int] | None:
    """The values of the number words ``word`` is made of, or None if it is not only those."""
    if not word:
        return []
    for morpheme in MORPHEMES:
        if word.startswith(morpheme):
            rest = split(word[len(morpheme) :])
            if rest is not None:
                return [WORDS[morpheme], *rest]
    return None


def value(parts: list[int]) -> int:
    total = current = 0
    for part in parts:
        if part == HUNDRED:
            current = (current or 1) * HUNDRED
        elif part in SCALES.values():
            total += (current or 1) * part
            current = 0
        else:
            current += part
    return total + current


def numeric(text: str) -> str:
    text = THOUSANDS.sub("", text)
    out: list[str] = []
    run: list[int] = []

    def flush(trail: str = "") -> None:
        if run:
            out.append(f"{value(run)}{trail}")
            run.clear()

    for token in text.split():
        core = token.rstrip(PUNCTUATION)
        trail = token[len(core) :]
        parts = split(core) if core == core.lstrip(PUNCTUATION) else None
        if not parts:
            flush()
            out.append(token)
        elif not run and out and out[-1].isdigit() and parts in ([s] for s in SCALES.values()):
            out[-1] = f"{int(out[-1]) * parts[0]}{trail}"  # "5 bin"
        else:
            run.extend(parts)
            if trail:  # punctuation ends the number: "üç,"
                flush(trail)
    flush()
    return " ".join(out)
