"""Reading a line from a CTC recogniser's frame-by-frame character distributions: greedily, or by
prefix beam search with the character language model weighed in (docs/benchmarks/ocr.md).

score(prefix) = log P_ctc + alpha * log P_lm + beta * characters. A digit is scored by the model's
probability of any digit in its place: whether a number fits there ("Sayı", not "Say1"), not
which number is common (a number is what the image shows). On pages of old books the language
model took the fine-tuned PP-OCRv6 from 92.5% of words to 94.8%, the stock model to 94.9%.
"""

import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from synapse.knowledge.charlm import CharLM

NEG = -1e30
DIGITS = "0123456789"


@dataclass(frozen=True)
class Search:
    alpha: float = 0.3  # weight of the language model
    beta: float = 2.0  # reward per character, against the model's preference for short text
    width: int = 8  # prefixes kept per frame
    prune: float = 1e-3  # characters below this probability in a frame are not tried
    top: int = 12  # characters per frame considered at all


def logsumexp(a: float, b: float) -> float:
    if a < b:
        a, b = b, a
    if b <= NEG:
        return a
    return a + math.log1p(math.exp(b - a))


def top_characters(
    probs: NDArray[np.float32], k: int
) -> tuple[NDArray[np.int64], NDArray[np.float32]]:
    """Per frame the k likeliest characters, likeliest first; a full sort of a character set of
    18,710 is what made reading slow."""
    k = min(k, probs.shape[1] - 1)
    top = np.argpartition(-probs, k, axis=1)[:, :k]
    kept = np.take_along_axis(probs, top, axis=1)
    order = np.argsort(-kept, axis=1, kind="stable")
    return np.take_along_axis(top, order, 1), np.take_along_axis(kept, order, 1)


def greedy(idx: NDArray[np.int64], chars: list[str]) -> str:
    out, last = [], 0
    for c in idx[:, 0]:
        if c not in (last, 0):
            out.append(chars[c])
        last = int(c)
    return "".join(out)


class LanguageScore:
    """log P_lm of a character after a prefix, cached for a page (lines repeat contexts)."""

    def __init__(self, lm: CharLM | None) -> None:
        self.lm = lm
        self.cache: dict[tuple[str, str], float] = {}

    def __call__(self, prefix: str, ch: str) -> float:
        if self.lm is None:
            return 0.0
        context = prefix[-(self.lm.order - 1) :]
        if len(prefix) < self.lm.order - 1:
            context = " " + context  # a line starts as a word does in the training text
        digit = ch.isdigit()
        k = (context, DIGITS if digit else ch)
        if k not in self.cache:
            if digit:  # whether a number fits here, not which number is common
                self.cache[k] = math.log(sum(self.lm.prob(context, d) for d in DIGITS))
            else:
                self.cache[k] = self.lm.logprob(context, ch)
        return self.cache[k]


def beam(
    idx: NDArray[np.int64],
    prob: NDArray[np.float32],
    chars: list[str],
    score: LanguageScore,
    search: Search,
) -> str:
    """CTC prefix beam search; the language model scores a character when it extends a prefix."""
    # prefix -> (log p of the paths ending in blank, log p of those ending in a character)
    beams: dict[str, tuple[float, float]] = {"": (0.0, NEG)}
    for t in range(idx.shape[0]):
        frame = [
            (int(c), float(p)) for c, p in zip(idx[t], prob[t], strict=True) if p >= search.prune
        ]
        if not frame:
            continue
        nxt: dict[str, list[float]] = defaultdict(lambda: [NEG, NEG])
        for prefix, (pb, pnb) in beams.items():
            total = logsumexp(pb, pnb)
            for c, p in frame:
                lp = math.log(p)
                if c == 0:  # blank
                    entry = nxt[prefix]
                    entry[0] = logsumexp(entry[0], total + lp)
                    continue
                ch = chars[c]
                entry = nxt[prefix + ch]
                bonus = search.alpha * score(prefix, ch) + search.beta
                if prefix and ch == prefix[-1]:
                    # a repeated character needs a blank between; without one it collapses
                    entry[1] = logsumexp(entry[1], pb + lp + bonus)
                    same = nxt[prefix]
                    same[1] = logsumexp(same[1], pnb + lp)
                else:
                    entry[1] = logsumexp(entry[1], total + lp + bonus)
        ranked = sorted(nxt.items(), key=lambda kv: -logsumexp(kv[1][0], kv[1][1]))[: search.width]
        beams = {k: (v[0], v[1]) for k, v in ranked}
    return max(beams.items(), key=lambda kv: logsumexp(kv[1][0], kv[1][1]))[0]


def read_line(
    probs: NDArray[np.float32], chars: list[str], score: LanguageScore, search: Search
) -> str:
    """One line's text from its frame distributions (frames x characters, index 0 the blank)."""
    idx, kept = top_characters(probs, search.top)
    if score.lm is None and search.width <= 1:
        return greedy(idx, chars)
    return beam(idx, kept.astype(np.float32), chars, score, search)
