"""Decode dumped CTC distributions (ctc_dump.py) into page texts: greedy, or prefix beam search
with a character language model (char_lm.py) weighed in.

    python eval/ocr/ctc_decode.py --dump DIR --out DIR [--lm FILE --alpha 0.3 --beta 2.0 --beam 8]

score(prefix) = log P_ctc + alpha * log P_lm + beta * characters. A digit is scored by the
model's probability of any digit in its place: whether a number fits there ("Sayı", not "Say1"),
not which number is common (a number is what the image shows). Lines are put in reading
order by reading_order.py (rows, and columns one after the other). The pages land in
OUT/<page>.txt for measure.py.

On 188 pages of Wikisource books kept out of fine-tuning, the fine-tuned PP-OCRv6 went from
92.5% of words greedy to 94.8% with the 6-gram model (alpha 0.3, beta 2.0; alpha 0.2 to 0.4
and beta 1.5 to 3 are a plateau, alpha 0.5 falls back), stock PP-OCRv6 to 94.9%.
"""

import argparse
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from char_lm import CharLM, load
from reading_order import reading_order

NEG = -1e30
DIGITS = "0123456789"


@dataclass(frozen=True)
class Search:
    alpha: float = 0.3  # weight of the language model
    beta: float = 2.0  # reward per character, against the model's preference for short text
    width: int = 8  # prefixes kept per frame
    prune: float = 1e-3  # characters below this probability in a frame are not tried


def logsumexp(a: float, b: float) -> float:
    if a < b:
        a, b = b, a
    if b <= NEG:
        return a
    return a + math.log1p(math.exp(b - a))


def greedy(idx: np.ndarray, chars: list[str]) -> str:
    out, last = [], 0
    for c in idx[:, 0]:
        if c not in (last, 0):
            out.append(chars[c])
        last = c
    return "".join(out)


def beam(
    idx: np.ndarray, prob: np.ndarray, chars: list[str], lm: CharLM | None, search: Search
) -> str:
    """CTC prefix beam search; the language model scores a character when it extends a prefix."""
    # prefix -> (log p of the paths ending in blank, log p of those ending in a character)
    beams: dict[str, tuple[float, float]] = {"": (0.0, NEG)}
    cache: dict[tuple[str, str], float] = {}

    def lm_score(prefix: str, ch: str) -> float:
        if lm is None:
            return 0.0
        context = prefix[-(lm.order - 1) :]
        if len(prefix) < lm.order - 1:
            context = " " + context  # a line starts as a word does in the training text
        digit = ch.isdigit()
        key = (context, DIGITS if digit else ch)
        if key not in cache:
            if digit:  # whether a number fits here, not which number is common
                cache[key] = math.log(sum(lm.prob(context, d) for d in DIGITS))
            else:
                cache[key] = lm.logprob(context, ch)
        return cache[key]

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
                bonus = search.alpha * lm_score(prefix, ch) + search.beta
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


def main() -> None:
    options = argparse.ArgumentParser()
    options.add_argument("--dump", type=Path, required=True)
    options.add_argument("--out", type=Path, required=True)
    options.add_argument("--lm", type=Path)
    options.add_argument("--alpha", type=float, default=0.3)
    options.add_argument("--beta", type=float, default=2.0)
    options.add_argument("--beam", type=int, default=8)
    args = options.parse_args()
    search = Search(alpha=args.alpha, beta=args.beta, width=args.beam)
    chars = (args.dump / "chars.txt").read_text(encoding="utf-8").split("\n")
    lm = load(args.lm) if args.lm else None
    args.out.mkdir(parents=True, exist_ok=True)
    pages = sorted(args.dump.glob("*.npz"))
    for f in pages:
        d = np.load(f)
        boxes = d["boxes"]
        texts = []
        for i in range(len(boxes)):
            idx, prob = d[f"idx_{i}"], d[f"prob_{i}"].astype(np.float32)
            texts.append(
                greedy(idx, chars)
                if lm is None and args.beam <= 1
                else beam(idx, prob, chars, lm, search)
            )
        (args.out / f"{f.stem}.txt").write_text(
            "\n".join(reading_order(list(zip(boxes.tolist(), texts, strict=True)))),
            encoding="utf-8",
        )
    print("decoded", len(pages), "pages to", args.out)


if __name__ == "__main__":
    main()
