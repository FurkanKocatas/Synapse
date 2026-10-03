"""Voting over aligned readings (vote.py) on cases small enough to follow by hand.

uv run --directory backend pytest ../eval/ocr/test_vote.py
"""

# ruff: noqa: S101  (pytest asserts)

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vote import vote


def test_the_reading_most_engines_give_wins() -> None:
    pivot = ["Meclis", "2026/35", "sayılı", "kararı", "kabul", "etti"]
    other = ["Meclis", "2026/36", "sayılı", "kararı", "kabul", "etti"]
    third = ["Meclis", "2026/35", "sayili", "kararı", "kabul", "etti"]
    assert vote([pivot, other, third]) == pivot


def test_a_word_the_pivot_missed_is_added_when_most_others_read_it() -> None:
    pivot = ["Meclis", "kararı", "kabul", "etti"]
    others = [
        ["Meclis", "bu", "kararı", "kabul", "etti"],
        ["Meclis", "bu", "kararı", "kabul", "etti"],
    ]
    assert vote([pivot, *others]) == ["Meclis", "bu", "kararı", "kabul", "etti"]
    alone = [["Meclis", "bu", "kararı", "kabul", "etti"], ["Meclis", "kararı", "kabul", "etti"]]
    assert vote([pivot, *alone]) == pivot


def test_turkish_letters_go_to_the_more_common_spelling_with_a_lexicon() -> None:
    readings = [["fıkra", "eklendi"], ["fikra", "eklendi"], ["fikra", "eklendi"]]
    assert vote(readings) == ["fikra", "eklendi"]
    frequency = {"fıkra": 4.2, "fikra": 1.1}
    assert vote(readings, frequency) == ["fıkra", "eklendi"]


def test_nothing_new_is_ever_written() -> None:
    readings = [["İzmir", "2026"], ["Izmir", "2O26"], ["lzmir", "2026"]]
    result = vote(readings, {"İzmir": 4.0})
    assert all(any(w in r for r in readings) for w in result)


def test_a_word_most_engines_did_not_read_is_left_out() -> None:
    looping = ["Meclis", "kararı", "kabul", "etti", "kabul", "etti", "kabul", "etti"]
    others = [["Meclis", "kararı", "kabul", "etti"], ["Meclis", "kararı", "kabul", "etti"]]
    assert vote([looping, *others]) == ["Meclis", "kararı", "kabul", "etti"]


def test_a_rare_word_the_engines_agree_on_is_kept() -> None:
    frequency = {"diş": 3.6, "dış": 4.6}
    readings = [["diş", "hekimi"], ["diş", "hekimi"], ["dış", "hekimi"]]
    assert vote(readings, frequency) == ["diş", "hekimi"]
    assert vote(readings, frequency, rule="first") == ["dış", "hekimi"]
