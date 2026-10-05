"""The packed character language model on texts small enough to count by hand."""

import math
from pathlib import Path

import pytest

from synapse.knowledge import charlm


def test_a_seen_continuation_beats_an_unseen_one() -> None:
    lm = charlm.train("malı alım malı alım malı", order=3)
    assert lm.prob("al", "ı") > 0.5
    assert lm.prob("al", "i") < 0.01


def test_probabilities_follow_witten_bell_from_the_empty_context_up() -> None:
    lm = charlm.train("ab", order=2)
    # counts: empty context -> a 1, b 1 (lambda 2/4); context "a" -> b 1 (lambda 1/2); the
    # context "\n" (the padding) -> a 1
    unigram = 0.5 * 1 / 2 + 0.5 * (1 / 3)  # vocabulary {a, b}: the floor is 1 / 3
    assert lm.prob("a", "b") == pytest.approx(0.5 * 1 + 0.5 * unigram)
    assert lm.prob("", "b") == pytest.approx(unigram)
    assert math.isclose(lm.logprob("a", "b"), math.log(lm.prob("a", "b")))


def test_a_context_never_seen_falls_back_to_the_shorter_ones() -> None:
    lm = charlm.train("abab", order=3)
    assert lm.prob("xa", "b") == lm.prob("a", "b")


def test_a_saved_model_loads_with_the_same_probabilities(tmp_path: Path) -> None:
    lm = charlm.train("Türkiye'de bir ev, iki ev.", order=4)
    lm.save(tmp_path / "lm.npz")
    loaded = charlm.CharLM.load(tmp_path / "lm.npz")
    for context, char in [("bir", " "), (" e", "v"), ("xyz", "ğ"), ("", "T")]:
        assert loaded.prob(context, char) == lm.prob(context, char)
    assert loaded.order == 4


def test_keys_are_the_same_in_every_process() -> None:
    # blake2b, not Python's hash, which changes from one process to the next: a model packed
    # in one process is read in another
    assert charlm.key("ev") == 0x3EF106EEBEFED97D
    assert charlm.pair_key("e", "v") != charlm.key("ev")
