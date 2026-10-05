"""The truth taken from Wikisource's rendering (wikisource.py) on small pieces of its HTML.

uv run --directory backend pytest ../eval/ocr/test_wikisource.py
"""

# ruff: noqa: S101  (pytest asserts)

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wikisource import from_html


def test_blocks_become_lines_and_styles_are_dropped() -> None:
    page = "<style>.x{}</style><p>Birinci satır</p><div>İkinci <b>satır</b></div>"
    assert from_html(page) == "Birinci satır\nİkinci satır"


def test_the_law_templates_clause_numbers_lose_their_f() -> None:
    page = (
        '<p><b>Madde 10</b></p><div><small><span id="fıkrano"><i>f1.</i> </span></small>'
        " Kabul eden Devlet, f1 bendinde</div>"
    )
    assert from_html(page) == "Madde 10\n1.  Kabul eden Devlet, f1 bendinde"


def article(number: int, *clauses: str) -> str:
    heading = f'<p><span id="Madde"><b>Madde {number}</b></span></p>'
    body = "".join(
        f'<div><span id="fıkrano"><i>f{i}.</i> </span> {text}</div>'
        for i, text in enumerate(clauses, 1)
    )
    return heading + body


def test_an_article_of_one_clause_has_no_number_unless_it_may_go_on_overleaf() -> None:
    page = article(17, "Tek") + article(18, "Bir", "İki") + article(19, "Son")
    lines = ["Madde 17", "Tek", "Madde 18", "1.  Bir", "2.  İki", "Madde 19", "1.  Son"]
    assert from_html(page) == "\n".join(lines)


def test_the_wikis_footnote_markers_are_dropped_and_the_notes_kept() -> None:
    page = (
        '<p>argo kullanımı<sup id="cite_ref-2" class="reference"><a href="#cite_note-2">'
        '<span class="cite-bracket">[</span>2<span class="cite-bracket">]</span></a></sup>'
        ' yönünden <sup>2</sup></p><p><span class="reference-text">Not metni.</span></p>'
    )
    assert from_html(page) == "argo kullanımı yönünden 2\nNot metni."
