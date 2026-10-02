"""The OCR measures (measure.py) on cases small enough to count by hand.

uv run --directory backend pytest ../eval/ocr/test_measure.py
"""

# ruff: noqa: S101, PLR2004  (pytest asserts; the counts are the cases)

import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from measure import page

TRUTH = "Meclis 2026/35 sayılı kararı\noybirliğiyle kabul etti.\nBütçe ışığında görüşüldü."


def test_a_perfect_reading_in_another_order_loses_no_word() -> None:
    reordered = "Bütçe ışığında görüşüldü.\nMeclis 2026/35 sayılı kararı\noybirliğiyle kabul etti."
    scored = page(TRUTH, reordered)
    assert scored.accuracy == 1.0
    assert scored.ordered_errors > 0


def test_a_word_read_wrongly_counts_once() -> None:
    scored = page(TRUTH, TRUTH.replace("kabul", "kabol"))
    assert scored.bag_errors == 1
    assert scored.truth_words == 10


def test_turkish_letters_lost_and_kept() -> None:
    scored = page("ışık", "isik")
    assert (scored.turkish, scored.turkish_kept) == (3, 0)
    decomposed = unicodedata.normalize("NFD", "oybirliğiyle")
    assert page("oybirliğiyle", decomposed).turkish_kept == 1


def test_identifiers_must_be_exact() -> None:
    assert page(TRUTH, TRUTH).ids_found == 1
    assert page(TRUTH, TRUTH.replace("2026/35", "2026/36")).ids_found == 0


def test_text_the_page_does_not_hold_is_invented_from_three_words_on() -> None:
    assert page(TRUTH, TRUTH + " ve ek olarak").invented == 3
    assert page(TRUTH, TRUTH + " ve ek").invented == 0


def test_a_repeated_phrase_is_a_loop_and_a_skipped_line_is_seen() -> None:
    looped = TRUTH + " kabul edildi oy birliği" * 3
    assert page(TRUTH, looped).loop
    skipped = page(TRUTH, "Meclis 2026/35 sayılı kararı\nBütçe ışığında görüşüldü.")
    assert (skipped.lines, skipped.lines_found) == (3, 2)
