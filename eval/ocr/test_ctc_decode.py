"""CTC decoding (ctc_decode.py) and the character language model (char_lm.py) on cases small
enough to follow by hand.

uv run --directory backend pytest ../eval/ocr/test_ctc_decode.py
"""

# ruff: noqa: S101  (pytest asserts)

import pickle
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from char_lm import CharLM, load
from ctc_decode import Search, beam, greedy, rows

CHARS = ["", "a", "l", "m", "ı", "i", " "]  # index 0 is the CTC blank


def frames(*rows_: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
    """Top-k arrays as ctc_dump.py writes them, from one {character: probability} per frame."""
    k = max(len(r) for r in rows_)
    idx = np.zeros((len(rows_), k), dtype=np.int32)
    prob = np.zeros((len(rows_), k), dtype=np.float32)
    for t, r in enumerate(rows_):
        for j, (ch, p) in enumerate(sorted(r.items(), key=lambda kv: -kv[1])):
            idx[t, j], prob[t, j] = CHARS.index(ch), p
    return idx, prob


def test_greedy_collapses_repeats_and_drops_blanks() -> None:
    idx, _ = frames({"a": 1}, {"a": 1}, {"": 1}, {"l": 1}, {"l": 1})
    assert greedy(idx, CHARS) == "al"


def test_a_blank_between_keeps_a_doubled_letter() -> None:
    idx, prob = frames({"a": 1}, {"l": 1}, {"": 1}, {"l": 1}, {"a": 1})
    assert greedy(idx, CHARS) == "alla"
    assert beam(idx, prob, CHARS, None, Search(alpha=0, beta=0)) == "alla"


def test_without_a_model_beam_search_sums_paths_greedy_cannot() -> None:
    # Greedy takes the likeliest character per frame: blank, blank. The two paths that read "a"
    # (a-blank, blank-a) together outweigh the one that reads nothing.
    idx, prob = frames({"": 0.6, "a": 0.4}, {"": 0.6, "a": 0.4})
    assert greedy(idx, CHARS) == ""
    assert beam(idx, prob, CHARS, None, Search(alpha=0, beta=0)) == "a"


def test_the_model_settles_a_letter_the_image_leaves_open() -> None:
    lm = CharLM(3)
    lm.train("malı alım malı alım malı")
    lm.finish()
    image = ({"m": 1}, {"a": 1}, {"l": 1}, {"ı": 0.45, "i": 0.55})
    idx, prob = frames(*image)
    assert beam(idx, prob, CHARS, None, Search(alpha=0, beta=0)) == "mali"
    assert beam(idx, prob, CHARS, lm, Search(alpha=1, beta=0)) == "malı"


def test_a_model_pickled_from_the_script_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lm = CharLM(2)
    lm.train("al")
    lm.finish()
    # `python char_lm.py train` pickles the class as __main__.CharLM
    monkeypatch.setattr(CharLM, "__module__", "__main__")
    monkeypatch.setattr(sys.modules["__main__"], "CharLM", CharLM, raising=False)
    data = pickle.dumps(lm)
    assert b"__main__" in data
    (tmp_path / "lm.pkl").write_bytes(data)
    assert load(tmp_path / "lm.pkl").prob("a", "l") == lm.prob("a", "l")


def test_a_file_holding_anything_else_is_refused(tmp_path: Path) -> None:
    (tmp_path / "other.pkl").write_bytes(pickle.dumps(Path("x")))
    with pytest.raises(pickle.UnpicklingError):
        load(tmp_path / "other.pkl")


def test_lines_are_read_in_rows_then_left_to_right() -> None:
    boxes = np.array([[200, 10, 300, 30], [0, 12, 100, 32], [0, 50, 100, 70]])
    assert rows(boxes, ["ikinci", "birinci", "alt"]) == ["birinci ikinci", "alt"]
