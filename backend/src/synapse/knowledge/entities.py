"""Typed entities in chunk text (ADR 0010, ingestion rule 6).

Exact identifier lookup (retrieval, step 7) needs identifiers found and written one way: a
decision number, a law number, a date, an amount, an article, a parcel. Each entity keeps the
text as written and a normalised value:

| kind | written | value |
|---|---|---|
| ``date`` | 15.03.2025, 3 Temmuz 2005 | 2025-03-15, 2005-07-03 |
| ``decision_number`` | 2026/35, Karar No: 123, E.2023/123 | 2026/35, 123, E.2023/123 |
| ``law_number`` | 5393 sayılı | 5393 |
| ``article`` | Madde 15, md. 15, 15 inci maddesi | 15 |
| ``amount`` | ₺2.500.000, 1.000.000,00 TL | 2500000.00 TRY, 1000000.00 TRY |
| ``parcel`` | 123 ada 4 parsel | 123/4 |

The words come from the language's data file; a tenant can add rules of its own. Matching runs
on the text lower-cased the Turkish way, which keeps its length, so offsets point into the
original text.
"""

import datetime
import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from synapse.knowledge.language import EntityWords, language
from synapse.knowledge.turkish import lower

EntityKind = Literal["date", "decision_number", "law_number", "article", "amount", "parcel"]
# A number written the Turkish way: dots between thousands, a comma before decimals.
_NUMBER = r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?"
_INTEGER = r"\d{1,3}(?:\.\d{3})+|\d+"


def _parcel(match: re.Match[str]) -> str:
    return f"{match.group(1).replace('.', '')}/{match.group(2).replace('.', '')}"


@dataclass(frozen=True)
class Entity:
    kind: EntityKind
    text: str
    value: str
    start: int


@dataclass(frozen=True)
class EntityRule:
    kind: EntityKind
    pattern: re.Pattern[str]
    # From the match to the normalised value; None drops the match (an impossible date).
    value: Callable[[re.Match[str]], str | None]


def _alternatives(words: tuple[str, ...]) -> str:
    return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))


def rules_for(words: EntityWords) -> tuple[EntityRule, ...]:
    months = {name: number for number, name in enumerate(words.months, start=1)}
    currencies = dict(words.currencies)
    symbols = [c for c in currencies if not c.isalpha()]
    names = [c for c in currencies if c.isalpha() or " " in c]
    suffixes = _alternatives(words.article_suffixes)

    def amount(match: re.Match[str]) -> str | None:
        number = match.group("number")
        currency = currencies[match.group("currency")]
        try:
            value = Decimal(number.replace(".", "").replace(",", "."))
        except InvalidOperation:
            return None
        return f"{value:.2f} {currency}"

    return (
        EntityRule(
            "date",
            re.compile(r"(?<![\d.])(\d{1,2})[./](\d{1,2})[./](\d{4})(?![\d.]\d)"),
            lambda m: _date(int(m.group(3)), int(m.group(2)), int(m.group(1))),
        ),
        EntityRule(
            "date",
            re.compile(rf"(?<!\d)(\d{{1,2}})\s+({_alternatives(tuple(months))})\s+(\d{{4}})\b"),
            lambda m: _date(int(m.group(3)), months[m.group(2)], int(m.group(1))),
        ),
        EntityRule(
            "decision_number",
            # "E.2023/123", "E. 2023/123", "E.: 2023/123": a court's docket and decision numbers.
            re.compile(rf"\b({_alternatives(words.court_marks)})\.\s?:?\s?(\d{{4}}/\d{{1,6}})\b"),
            lambda m: f"{m.group(1).upper()}.{m.group(2)}",
        ),
        EntityRule(
            "decision_number",
            re.compile(rf"\b(?:{_alternatives(words.decision_words)})\s*[:.]?\s*(\d+(?:/\d+)?)\b"),
            lambda m: m.group(1),
        ),
        EntityRule(
            "decision_number",
            re.compile(r"(?<![\d./])((?:19|20)\d{2}/\d{1,6})(?![\d/])"),
            lambda m: m.group(1),
        ),
        EntityRule(
            "law_number",
            re.compile(rf"(?<![\d.])(\d{{3,5}})\s+{re.escape(words.numbered_law)}\b"),
            lambda m: m.group(1),
        ),
        EntityRule(
            "article",
            re.compile(rf"\b(?:{_alternatives(words.article_words)})\.?\s*(\d{{1,4}})\b"),
            lambda m: m.group(1),
        ),
        EntityRule(
            "article",
            # "15 inci maddesi"; the ordinal suffix is required, or "3 maddelik" would match.
            re.compile(
                rf"(?<![\d.])(\d{{1,4}})\s*'?(?:{suffixes})\s+{re.escape(words.article_noun)}"
            ),
            lambda m: m.group(1),
        ),
        EntityRule(
            "amount",
            re.compile(
                rf"(?P<currency>{_alternatives(tuple(symbols))})\s?(?P<number>{_NUMBER})(?![\d])"
            ),
            amount,
        ),
        EntityRule(
            "amount",
            re.compile(
                rf"(?<![\d.,])(?P<number>{_NUMBER})\s?(?P<currency>{_alternatives(tuple(names))})\b"
            ),
            amount,
        ),
        EntityRule(
            "parcel",
            re.compile(
                rf"(?<![\d.])({_INTEGER})\s*{re.escape(words.parcel_block)}[,\s]+({_INTEGER})\s*"
                rf"{re.escape(words.parcel)}"
            ),
            _parcel,
        ),
        EntityRule(
            "parcel",
            re.compile(
                rf"\b{re.escape(words.parcel_block)}\s*[:.]?\s*({_INTEGER})[,\s]+"
                rf"{re.escape(words.parcel)}\s*[:.]?\s*({_INTEGER})"
            ),
            _parcel,
        ),
    )


DEFAULT_RULES = rules_for(language().entities)


def _date(year: int, month: int, day: int) -> str | None:
    try:
        return datetime.date(year, month, day).isoformat()
    except ValueError:
        return None


def extract(text: str, rules: tuple[EntityRule, ...] = DEFAULT_RULES) -> list[Entity]:
    """Entities in order of appearance; one per span, the first rule that claims it winning."""
    folded = lower(text)
    source = text if len(folded) == len(text) else folded
    found: list[Entity] = []
    taken: list[tuple[int, int]] = []
    for rule in rules:
        for match in rule.pattern.finditer(folded):
            span = match.span()
            if any(span[0] < end and start < span[1] for start, end in taken):
                continue
            value = rule.value(match)
            if value is None:
                continue
            taken.append(span)
            found.append(Entity(rule.kind, source[span[0] : span[1]], value, span[0]))
    return sorted(found, key=lambda e: e.start)
