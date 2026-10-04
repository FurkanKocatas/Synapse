"""Decode dumped CTC distributions (ctc_dump.py) into page texts: greedy, or prefix beam search
with a character language model (char_lm.py) weighed in.

    python eval/ocr/ctc_decode.py --dump DIR --out DIR [--lm FILE --alpha 0.3 --beta 2.0 --beam 8]

score(prefix) = log P_ctc + alpha * log P_lm + beta * characters. The language model's weight is
zero for digits (a number is what the image shows, not what is common). Lines are put in reading
order as the PP-OCR runner does (rows by vertical centre, left to right). The pages land in
OUT/<page>.txt for measure.py.

On 200 pages of Wikisource books kept out of fine-tuning, the fine-tuned PP-OCRv6 went from
89.5% of words greedy to 91.6-91.7% with the 6-gram model at alpha 0.3 and beta 1 to 3; beam
search without the model gave 89.5%, alpha 0.5 fell back to 90.9%.
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

NEG = -1e30


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
        if lm is None or ch.isdigit():
            return 0.0
        key = (prefix[-(lm.order - 1) :], ch)
        if key not in cache:
            # a line's first characters follow a space, as a word's do in the training text
            cache[key] = lm.logprob(" " + key[0] if len(prefix) < lm.order - 1 else key[0], ch)
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


def rows(boxes: np.ndarray, texts: list[str]) -> list[str]:
    items = sorted(
        ((b[1] + b[3]) / 2, b[0], b[3] - b[1], t) for b, t in zip(boxes, texts, strict=True) if t
    )
    out: list[list[tuple[float, str]]] = []
    centre = None
    for y, x, height, text in items:
        if centre is None or y - centre > height / 2:
            out.append([])
            centre = y
        out[-1].append((x, text))
    return [" ".join(t for _, t in sorted(row)) for row in out]


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
        (args.out / f"{f.stem}.txt").write_text("\n".join(rows(boxes, texts)), encoding="utf-8")
    print("decoded", len(pages), "pages to", args.out)


if __name__ == "__main__":
    main()
