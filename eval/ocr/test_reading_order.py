"""Reading order (reading_order.py) on page layouts small enough to draw by hand.

uv run --directory backend pytest ../eval/ocr/test_reading_order.py
"""

# ruff: noqa: S101  (pytest asserts)

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reading_order import gutter, reading_order, rows


def column(x0: int, x1: int, top: int, n: int, name: str) -> list[tuple[list[int], str]]:
    return [([x0, top + 40 * i, x1, top + 40 * i + 30], f"{name}{i}") for i in range(n)]


def test_lines_are_read_in_rows_then_left_to_right() -> None:
    items = [
        ([200, 10, 300, 30], "second"),
        ([0, 12, 100, 32], "first"),
        ([0, 50, 100, 70], "below"),
    ]
    assert rows(items) == ["first second", "below"]


def test_two_columns_are_read_one_after_the_other() -> None:
    page = column(0, 900, 100, 8, "L") + column(1000, 1900, 100, 8, "R")
    assert reading_order(page) == [f"L{i}" for i in range(8)] + [f"R{i}" for i in range(8)]


def test_a_title_across_the_columns_is_read_first_and_a_footnote_last() -> None:
    page = [
        ([300, 20, 1600, 60], "title"),
        *column(0, 900, 100, 8, "L"),
        *column(1000, 1900, 100, 8, "R"),
        ([0, 500, 1900, 530], "note"),
    ]
    order = reading_order(page)
    assert order[0] == "title"
    assert order[-1] == "note"
    assert order[1:9] == [f"L{i}" for i in range(8)]


def test_columns_below_a_full_width_paragraph_start_a_new_band() -> None:
    page = (
        column(0, 1900, 0, 3, "P") + column(0, 900, 200, 8, "L") + column(1000, 1900, 200, 8, "R")
    )
    order = reading_order(page)
    assert order[:3] == ["P0", "P1", "P2"]
    assert order[3:11] == [f"L{i}" for i in range(8)]


def test_one_column_of_text_has_no_gutter() -> None:
    assert gutter([b for b, _ in column(0, 1900, 0, 20, "P")]) is None


def test_a_two_column_table_of_short_cells_is_read_row_by_row() -> None:
    keys = [([0, 40 * i, 150, 40 * i + 30], f"key{i}") for i in range(10)]
    values = [([1000, 40 * i, 1200, 40 * i + 30], f"value{i}") for i in range(10)]
    order = reading_order(keys + values)
    assert order[:2] == ["key0 value0", "key1 value1"]


def test_ragged_verse_on_the_left_is_not_a_column() -> None:
    verse = [([0, 40 * i, 300 + 50 * (i % 3), 40 * i + 30], f"v{i}") for i in range(12)]
    assert gutter([b for b, _ in verse]) is None
