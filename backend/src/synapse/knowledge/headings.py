"""Section levels from the conventions of Turkish documents (ADR 0010, ingestion rule 7).

Chunks never cross a level 1 or 2 heading, so levels must be right, and fonts do not give them:
layout parsers mark headings but give every one the same level, and a PDF text layer marks
nothing. Turkish legislation and public documents number their sections in words and digits
instead ("BİRİNCİ KISIM", "İKİNCİ BÖLÜM", "MADDE 5 -", "3.2.1."), which is what these rules
read. The words come from the language's data file (knowledge/language.py); a tenant with other
conventions passes other rules.
"""

import re
from dataclasses import dataclass

from synapse.knowledge.language import Language, language
from synapse.knowledge.structure import Block, BlockKind
from synapse.knowledge.turkish import lower

# A heading is short and does not end like a sentence; longer lines are running text.
MAX_HEADING_CHARS = 120
# A line a parser marked as a heading that no rule recognises.
UNNUMBERED_LEVEL = 3
MOSTLY_CAPITALS = 0.8
# A heading of at most this many words ("BİRİNCİ KISIM") may have its title on the next line:
# a line of at most TITLE_CHARS, most of whose words (TITLE_CASE) start with a capital.
BARE_HEADING = 3
TITLE_CHARS = 60
TITLE_CASE = 0.6
# Legislation separates an article's number from its text with a hyphen, a colon, a full stop,
# a bracket, and most often an en or em dash.
_SEPARATORS = "-:.)" + chr(0x2013) + chr(0x2014)
_LABEL_END = " " + _SEPARATORS
# "1.", "2)", "a)", or a bullet at the start of a line opens a list item.
_LIST_MARKER = re.compile(r"(?:\d{1,2}[.)]|[^\W\d_][.)]|[-•*▪●])\s+\S")
# A number and a hyphen at the end of a line, before a line that starts with a digit: one
# identifier broken at the line end ("12/7/2013-" "6495/73 md.)", "E-81912396-105.04-"
# "2026.106304.1"), or a range ("(2024-" "2026)"). The hyphen belongs to it.
_NUMBER_HYPHEN_END = re.compile(r"\d-$")


@dataclass(frozen=True)
class HeadingRule:
    """``pattern`` is matched from the start of the line, lower-cased the Turkish way.

    - ``level``: the section level; ``None`` means the depth of the number in group 1 plus
      ``offset`` ("3." is 2, "3.2." is 3 with the default offset 1).
    - ``in_text``: the pattern opens a section even at the start of running text; the label is
      the matched part ("Madde 5" from "Madde 5- Bu Kanun ...").
    - ``capitals``: in unmarked text (a PDF text layer), the line must be mostly capitals, which
      tells "9. MALİ YÖNETİM" from the list item "1. Uygun mülkiyet bulunamaması".
    """

    name: str
    pattern: re.Pattern[str]
    level: int | None = None
    in_text: bool = False
    capitals: bool = False
    offset: int = 1


def rules_for(words: Language) -> tuple[HeadingRule, ...]:
    ordinals = "|".join(re.escape(o) for o in words.ordinals)
    prefixes = "|".join(re.escape(p) for p in words.article_prefixes)
    article = (
        rf"(?:(?:{prefixes})\s+)?{re.escape(words.article)}\s+\d+(?:/\w)?"
        rf"\s*[{re.escape(_SEPARATORS)}]"
    )
    return (
        HeadingRule("part", re.compile(rf"(?:{ordinals})\s+{re.escape(words.part)}\b"), level=1),
        HeadingRule(
            "chapter", re.compile(rf"(?:{ordinals})\s+{re.escape(words.chapter)}\b"), level=2
        ),
        HeadingRule("article", re.compile(article), level=3, in_text=True),
        # "9. MALİ YÖNETİM", "3.2 HEDEFLER", "3.2.1."; a bare "1 " is not a section number: in a
        # PDF text layer it starts the row of a numbered table ("1 AYHAN ŞAHİN 802 ...").
        HeadingRule(
            "numbered",
            re.compile(r"(\d{1,2}\.(?:\d{1,2}\.){0,3}|\d{1,2}(?:\.\d{1,2}){1,3})\s+\S"),
            capitals=True,
        ),
        HeadingRule("lettered", re.compile(r"[^\W\d_]\.\s+\S"), level=2, capitals=True),
    )


DEFAULT_RULES = rules_for(language("tr"))


@dataclass(frozen=True)
class Section:
    level: int
    label: str
    # The line is running text that opens a section ("Madde 5- Bu Kanun ..."), not a title.
    running: bool = False


def section(
    line: str, *, marked: bool, rules: tuple[HeadingRule, ...] = DEFAULT_RULES
) -> Section | None:
    """The section a line opens, or None.

    ``marked``: the parser marked the line as a heading (a Word heading style, a layout model).
    Unmarked lines open a section only through an ``in_text`` rule, or when they look like a
    title: short, no sentence end, and mostly capitals where the rule asks for it.
    """
    text = " ".join(line.split())
    folded = lower(text)
    title_like = len(text) <= MAX_HEADING_CHARS and not text.endswith((".", ",", ";", ":"))
    for rule in rules:
        match = rule.pattern.match(folded)
        if match is None:
            continue
        if rule.in_text:
            opens = rule.level or UNNUMBERED_LEVEL
            if marked:
                return Section(opens, text)
            return Section(opens, text[: match.end()].rstrip(_LABEL_END), running=True)
        if not (marked or (title_like and (not rule.capitals or _mostly_capitals(text)))):
            continue
        level = rule.level
        if level is None:
            level = len(re.findall(r"\d+", match.group(1))) + rule.offset
        return Section(level, text)
    return Section(UNNUMBERED_LEVEL, text) if marked else None


def blocks_from_text(
    text: str, page: int, rules: tuple[HeadingRule, ...] = DEFAULT_RULES
) -> list[Block]:
    """Blocks from plain text with one line per printed line (a PDF text layer, OCR output).

    Lines are joined into paragraphs; a paragraph ends at a blank line, before a title line,
    before an article, or where a line ends a sentence and the next starts with a capital or a
    digit. A word hyphenated across lines is joined; a number that ends a line with a hyphen
    and continues with a digit on the next is joined keeping the hyphen, so an identifier
    ("12/7/2013-6495/73", "E-81912396-105.04-2026.106304.1") stays one token.
    """
    blocks: list[Block] = []
    lines: list[str] = []
    opened: Section | None = None
    kind: BlockKind = "paragraph"

    def flush() -> None:
        nonlocal lines, opened, kind
        if lines:
            level = opened.level if opened else None
            label = opened.label if opened else None
            blocks.append(Block(kind, " ".join(lines), page, level=level, label=label))
        lines, opened, kind = [], None, "paragraph"

    for raw in text.split("\n"):
        line = " ".join(raw.split())
        if not line:
            flush()
            continue
        if lines and _NUMBER_HYPHEN_END.search(lines[-1]) and line[:1].isdigit():
            lines[-1] += line
            continue
        found = section(line, marked=False, rules=rules)
        if found is not None and not found.running:
            flush()
            blocks.append(Block("heading", line, page, level=found.level))
            continue
        if found is None and not lines and _names_the_heading_above(blocks, line):
            # "BİRİNCİ KISIM" on one line and its title "Genel Hükümler" on the next.
            heading = blocks[-1]
            blocks[-1] = Block("heading", f"{heading.text} {line}", page, level=heading.level)
            continue
        listed = found is None and _LIST_MARKER.match(line) is not None
        if (
            found is not None
            or listed
            or (lines and _ends_sentence(lines[-1]) and _starts_new(line))
        ):
            flush()
            opened = found
            kind = "list_item" if listed else "paragraph"
        if lines and lines[-1].endswith("-") and line[:1].islower():
            lines[-1] = lines[-1][:-1] + line
        else:
            lines.append(line)
    flush()
    return blocks


def _names_the_heading_above(blocks: list[Block], line: str) -> bool:
    """A bare numbered heading ("BİRİNCİ KISIM") just above, and a short title-cased line."""
    if not blocks or blocks[-1].kind != "heading" or len(blocks[-1].text.split()) > BARE_HEADING:
        return False
    if len(line) > TITLE_CHARS or line.endswith((".", ",", ";", ":")):
        return False
    words = line.split()
    return sum(w[:1].isupper() for w in words) >= TITLE_CASE * len(words)


def _ends_sentence(line: str) -> bool:
    return line.endswith((".", ":", "!", "?"))


def _starts_new(line: str) -> bool:
    first = line.lstrip("\"'([“‘-•*")[:1]
    return first.isupper() or first.isdigit()


def _mostly_capitals(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    return bool(letters) and sum(ch.isupper() for ch in letters) >= MOSTLY_CAPITALS * len(letters)
