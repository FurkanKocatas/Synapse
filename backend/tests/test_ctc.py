"""Reading a line from CTC frame distributions, greedily and with the language model, on frames
small enough to follow by hand."""

import numpy as np
from numpy.typing import NDArray

from synapse.knowledge import charlm
from synapse.knowledge.ctc import LanguageScore, Search, read_line, top_characters

CHARS = ["", "a", "l", "m", "ı", "i", " ", "1", "2"]  # index 0 is the CTC blank
PLAIN = Search(alpha=0, beta=0)


def frames(*rows: dict[str, float]) -> NDArray[np.float32]:
    """A (frames x characters) distribution from one {character: probability} per frame."""
    out = np.zeros((len(rows), len(CHARS)), dtype=np.float32)
    for t, row in enumerate(rows):
        for ch, p in row.items():
            out[t, CHARS.index(ch)] = p
    return out


def test_greedy_collapses_repeats_and_drops_blanks() -> None:
    probs = frames({"a": 1}, {"a": 1}, {"": 1}, {"l": 1}, {"l": 1})
    assert read_line(probs, CHARS, LanguageScore(None), Search(width=1)) == "al"


def test_a_blank_between_keeps_a_doubled_letter() -> None:
    probs = frames({"a": 1}, {"l": 1}, {"": 1}, {"l": 1}, {"a": 1})
    assert read_line(probs, CHARS, LanguageScore(None), Search(width=1)) == "alla"
    assert read_line(probs, CHARS, LanguageScore(None), PLAIN) == "alla"


def test_beam_search_sums_paths_greedy_cannot() -> None:
    # Greedy takes blank, blank. The two paths that read "a" (a-blank, blank-a) together
    # outweigh the one that reads nothing.
    probs = frames({"": 0.6, "a": 0.4}, {"": 0.6, "a": 0.4})
    assert read_line(probs, CHARS, LanguageScore(None), Search(width=1)) == ""
    assert read_line(probs, CHARS, LanguageScore(None), PLAIN) == "a"


def test_the_model_settles_a_letter_the_image_leaves_open() -> None:
    lm = charlm.train("malı alım malı alım malı", order=3)
    probs = frames({"m": 1}, {"a": 1}, {"l": 1}, {"ı": 0.45, "i": 0.55})
    assert read_line(probs, CHARS, LanguageScore(None), PLAIN) == "mali"
    assert read_line(probs, CHARS, LanguageScore(lm), Search(alpha=1, beta=0)) == "malı"


def test_a_digit_is_not_free_where_no_number_fits() -> None:
    lm = charlm.train("malı alım malı 12 21 malı", order=3)
    probs = frames({"m": 1}, {"a": 1}, {"l": 1}, {"ı": 0.45, "1": 0.55})
    assert read_line(probs, CHARS, LanguageScore(lm), Search(alpha=1, beta=0)) == "malı"


def test_the_model_does_not_choose_between_digits() -> None:
    lm = charlm.train("12 12 12 12", order=3)
    probs = frames({"1": 1}, {"": 1}, {"1": 0.55, "2": 0.45})
    assert read_line(probs, CHARS, LanguageScore(lm), Search(alpha=1, beta=0)) == "11"


def test_the_likeliest_characters_come_first() -> None:
    probs = frames({"a": 0.1, "l": 0.6, "m": 0.3})
    idx, kept = top_characters(probs, 2)
    assert [CHARS[i] for i in idx[0]] == ["l", "m"]
    assert kept[0].tolist() == [np.float32(0.6), np.float32(0.3)]
