"""A character language model of Turkish for decoding OCR (docs/benchmarks/ocr.md): interpolated
Witten-Bell n-grams, trained by eval/ocr/char_lm.py and packed into sorted arrays.

The trained model's Python dictionaries take 1.1 GB; packed, the same probabilities take about
90 MB, in float64 so that decoding gives what the trained model gives, to the last bit. Every
context keeps the weight it leaves to its shorter context (1 - lambda), every seen (context,
character) pair its own share (lambda * count / total), each under a 64-bit hash of its
strings. A probability is built as in training, from the empty context up:

    p = 1 / (V + 1);  for each context length n: p = share_n(c) + backoff_n * p

stopping at the first context the training text never had (no longer one can have it either).
"""

import hashlib
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

_SEPARATOR = "\x00"  # between a context and its character in a pair's key; not in any text


def key(text: str) -> int:
    """A 64-bit hash that, unlike ``hash``, is the same in every process."""
    return int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "little")


def pair_key(context: str, char: str) -> int:
    return key(context + _SEPARATOR + char)


@dataclass(frozen=True)
class CharLM:
    order: int
    vocabulary: int  # distinct characters in the training text
    context_keys: NDArray[np.uint64]  # sorted
    backoff: NDArray[np.float64]  # 1 - lambda, per context
    pair_keys: NDArray[np.uint64]  # sorted
    share: NDArray[np.float64]  # lambda * count / total, per seen pair

    @classmethod
    def load(cls, path: Path) -> CharLM:
        with np.load(path) as arrays:
            return cls(
                order=int(arrays["order"]),
                vocabulary=int(arrays["vocabulary"]),
                context_keys=arrays["context_keys"],
                backoff=arrays["backoff"],
                pair_keys=arrays["pair_keys"],
                share=arrays["share"],
            )

    def save(self, path: Path) -> None:
        np.savez(
            path,
            order=np.int64(self.order),
            vocabulary=np.int64(self.vocabulary),
            context_keys=self.context_keys,
            backoff=self.backoff,
            pair_keys=self.pair_keys,
            share=self.share,
        )

    def prob(self, context: str, char: str) -> float:
        p = 1.0 / (self.vocabulary + 1)
        for n in range(min(self.order, len(context) + 1)):
            ctx = context[len(context) - n :]
            found = _find(self.context_keys, key(ctx))
            if found is None:
                break
            seen = _find(self.pair_keys, pair_key(ctx, char))
            share = float(self.share[seen]) if seen is not None else 0.0
            p = share + float(self.backoff[found]) * p
        return p

    def logprob(self, context: str, char: str) -> float:
        return math.log(self.prob(context, char))


def _find(keys: NDArray[np.uint64], value: int) -> int | None:
    i = int(np.searchsorted(keys, np.uint64(value)))
    return i if i < len(keys) and int(keys[i]) == value else None


Counts = Sequence[Mapping[str, Mapping[str, int]]]  # per context length: context -> char -> count


def train(text: str, order: int) -> CharLM:
    """A model of ``text``, counted as eval/ocr/char_lm.py counts (the text padded with line
    breaks), so the two give the same probabilities; the full model is trained there."""
    counts: list[defaultdict[str, Counter[str]]] = [defaultdict(Counter) for _ in range(order)]
    padded = "\n" * (order - 1) + text
    for n in range(order):  # n = context length
        for i in range(order - 1, len(padded)):
            counts[n][padded[i - n : i]][padded[i]] += 1
    return from_counts(counts, len(set(text)))


def from_counts(counts: Counts, vocabulary: int) -> CharLM:
    """Packed from n-gram counts. Each share and backoff is computed as the trained model's
    ``prob`` computes it, so the two agree to the last bit."""
    n_contexts = sum(len(table) for table in counts)
    n_pairs = sum(len(chars) for table in counts for chars in table.values())
    context_keys = np.empty(n_contexts, dtype=np.uint64)
    backoff = np.empty(n_contexts, dtype=np.float64)
    pair_keys = np.empty(n_pairs, dtype=np.uint64)
    share = np.empty(n_pairs, dtype=np.float64)
    i = j = 0
    for table in counts:
        for ctx, chars in table.items():
            total = sum(chars.values())
            lam = total / (total + len(chars))
            context_keys[i], backoff[i] = key(ctx), 1 - lam
            i += 1
            for char, count in chars.items():
                pair_keys[j], share[j] = pair_key(ctx, char), lam * count / total
                j += 1
    by_context, by_pair = np.argsort(context_keys), np.argsort(pair_keys)
    model = CharLM(
        order=len(counts),
        vocabulary=vocabulary,
        context_keys=context_keys[by_context],
        backoff=backoff[by_context],
        pair_keys=pair_keys[by_pair],
        share=share[by_pair],
    )
    for keys in (model.context_keys, model.pair_keys):
        if (np.diff(keys) == 0).any():
            raise ValueError("two strings share a 64-bit hash")
    return model
