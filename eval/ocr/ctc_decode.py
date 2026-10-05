"""Decode dumped CTC distributions (ctc_dump.py) into page texts with the product's decoder
(synapse.knowledge.ctc) and reading order (synapse.knowledge.reading): greedy, or prefix beam
search with the packed character language model (char_lm.py pack).

    uv run --directory backend python ../eval/ocr/ctc_decode.py --dump DIR --out DIR \
        [--lm FILE.npz --alpha 0.3 --beta 2.0 --beam 8]

The pages land in OUT/<page>.txt for measure.py. Results are in docs/benchmarks/ocr.md.
"""

import argparse
from pathlib import Path

import numpy as np
from synapse.knowledge.charlm import CharLM
from synapse.knowledge.ctc import LanguageScore, Search, beam, greedy
from synapse.knowledge.reading import reading_order


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
    lm = CharLM.load(args.lm) if args.lm else None
    args.out.mkdir(parents=True, exist_ok=True)
    pages = sorted(args.dump.glob("*.npz"))
    for f in pages:
        d = np.load(f)
        boxes = d["boxes"]
        score = LanguageScore(lm)
        texts = []
        for i in range(len(boxes)):
            idx, prob = d[f"idx_{i}"], d[f"prob_{i}"].astype(np.float32)
            if lm is None and search.width <= 1:
                texts.append(greedy(idx, chars))
            else:
                texts.append(beam(idx, prob, chars, score, search))
        lines = reading_order(list(zip(boxes.tolist(), texts, strict=True)))
        (args.out / f"{f.stem}.txt").write_text("\n".join(lines), encoding="utf-8")
    print("decoded", len(pages), "pages to", args.out)


if __name__ == "__main__":
    main()
