"""A page parser's Markdown and HTML as the plain text measure.py compares with a page's truth.

Markup is not text the page holds: heading and list markers, emphasis, table rules and pipes,
HTML tags and image placeholders go; a table becomes its cells' text, row by row; formulas stay
as written. What the parser read is not changed.
"""

import html
import re

_IMAGE = re.compile(r"<img[^>]*>|!\[[^\]]*\]\([^)]*\)", re.IGNORECASE)
_CELL_END = re.compile(r"</t[dh]\s*>", re.IGNORECASE)
_ROW_END = re.compile(r"</tr\s*>|<br\s*/?>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_BULLET = re.compile(r"^\s*[-*+]\s+(?=\S)", re.MULTILINE)
_QUOTE = re.compile(r"^\s*>\s?", re.MULTILINE)
_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$", re.MULTILINE)
# Emphasis only between word boundaries: "dosya_adi_2026" is a name, not emphasis.
_EMPHASIS = re.compile(r"(?<!\w)(\*\*|__|\*|_)(?=\S)(.+?)(?<=\S)\1(?!\w)")
_CODE = re.compile(r"`([^`]*)`")


def plain(markup: str) -> str:
    text = _IMAGE.sub(" ", markup)
    text = _CELL_END.sub(" ", text)
    text = _ROW_END.sub("\n", text)
    text = html.unescape(_TAG.sub(" ", text))
    text = _RULE.sub("", text)
    text = text.replace("|", " ")
    text = _HEADING.sub("", text)
    text = _QUOTE.sub("", text)
    text = _BULLET.sub("", text)
    text = _EMPHASIS.sub(r"\2", text)
    text = _CODE.sub(r"\1", text)
    # A numbered list item keeps its number: "1." may be the page's own numbering.
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()
