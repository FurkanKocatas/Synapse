"""Training the character language model (char_lm.py): its pickle, and the packed model the
product loads giving the same probabilities.

uv run --directory backend pytest ../eval/ocr/test_char_lm.py
"""

# ruff: noqa: S101  (pytest asserts)

import pickle
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from char_lm import CharLM, load, pack
from synapse.knowledge import charlm


def trained(text: str, order: int) -> CharLM:
    lm = CharLM(order)
    lm.train(text)
    lm.finish()
    return lm


def test_the_packed_model_gives_the_trained_models_probabilities(tmp_path: Path) -> None:
    text = "Türkiye'de bir ev, iki ev. Madde 17: tarafından kabul edilir."
    lm = trained(text, 4)
    pack(lm, tmp_path / "lm.npz")
    packed = charlm.CharLM.load(tmp_path / "lm.npz")
    for context in ["", "e", " e", "bir", "tar", "xyz", "Mad"]:
        for char in "evrdaıü :Q":
            assert packed.prob(context, char) == lm.prob(context, char)
    # and the backend's own training counts the same way
    assert charlm.train(text, 4).prob("tar", "a") == lm.prob("tar", "a")


def test_a_model_pickled_from_the_script_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lm = trained("al", 2)
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
