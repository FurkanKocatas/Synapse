"""A character n-gram language model of Turkish (interpolated Witten-Bell), trained on Turkish
Wikipedia text, for scoring OCR hypotheses character by character (ctc_decode.py).

    python eval/ocr/char_lm.py train --parquet FILE --out FILE [--order 6] [--chars 15000000]
    python eval/ocr/char_lm.py probe --lm FILE
    uv run --directory backend python ../eval/ocr/char_lm.py pack --lm FILE --out FILE.npz

Characters are kept as written (case and Turkish letters); runs of whitespace become one space.
Memory grows with the order and the text: order 6 on 15 million characters is 67 MB on disk and
about 1 GB loaded; training order 7 on 30 million went past 6 GB.
"""

import argparse
import math
import pickle
import random
import re
from collections import Counter, defaultdict
from pathlib import Path


class CharLM:
    def __init__(self, order: int) -> None:
        self.order = order
        self.counts: list[dict[str, Counter]] = [defaultdict(Counter) for _ in range(order)]
        self.vocab: set[str] = set()

    def train(self, text: str) -> None:
        self.vocab.update(text)
        padded = "\n" * (self.order - 1) + text
        for n in range(self.order):  # n = context length
            table = self.counts[n]
            for i in range(self.order - 1, len(padded)):
                table[padded[i - n : i]][padded[i]] += 1

    def finish(self) -> None:
        """Totals and type counts per context, for Witten-Bell."""
        self.totals = [{c: sum(v.values()) for c, v in t.items()} for t in self.counts]
        self.types = [{c: len(v) for c, v in t.items()} for t in self.counts]
        self.counts = [dict(t) for t in self.counts]

    def prob(self, context: str, char: str) -> float:
        p = 1.0 / (len(self.vocab) + 1)
        for n in range(self.order):
            if n and len(context) < n:
                break
            ctx = context[len(context) - n :] if n else ""
            total = self.totals[n].get(ctx)
            if not total:
                continue
            lam = total / (total + self.types[n][ctx])
            p = lam * self.counts[n][ctx].get(char, 0) / total + (1 - lam) * p
        return p

    def logprob(self, context: str, char: str) -> float:
        return math.log(self.prob(context, char))


class _Unpickler(pickle.Unpickler):
    """Loads a CharLM and nothing else: the only classes in the file are CharLM and Counter."""

    def find_class(self, module: str, name: str) -> type:
        if name == "CharLM":  # pickled as __main__.CharLM when this file ran as a script
            return CharLM
        if (module, name) == ("collections", "Counter"):
            return Counter
        raise pickle.UnpicklingError(f"{module}.{name} is not part of a CharLM")


def load(path: Path) -> CharLM:
    with path.open("rb") as f:
        return _Unpickler(f).load()


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def pack(lm: CharLM, out: Path) -> None:
    """The model as the product loads it (synapse.knowledge.charlm): sorted 64-bit hashes and
    float64 shares, computed as ``prob`` computes them so the two agree to the last bit."""
    from synapse.knowledge import charlm  # noqa: PLC0415 - only packing needs the backend

    packed = charlm.from_counts(lm.counts, len(lm.vocab))
    packed.save(out)
    contexts, pairs = len(packed.context_keys), len(packed.pair_keys)
    print(f"packed {contexts:,} contexts and {pairs:,} pairs into {out}")


def main() -> None:
    options = argparse.ArgumentParser()
    sub = options.add_subparsers(dest="command", required=True)
    tr = sub.add_parser("train")
    tr.add_argument("--parquet", type=Path, required=True)
    tr.add_argument("--out", type=Path, required=True)
    tr.add_argument("--order", type=int, default=6)
    tr.add_argument("--chars", type=int, default=15_000_000)
    pr = sub.add_parser("probe")
    pr.add_argument("--lm", type=Path, required=True)
    pa = sub.add_parser("pack")
    pa.add_argument("--lm", type=Path, required=True)
    pa.add_argument("--out", type=Path, required=True)
    args = options.parse_args()
    if args.command == "pack":
        pack(load(args.lm), args.out)
        return
    if args.command == "train":
        import pyarrow.parquet as pq  # noqa: PLC0415 - only training reads parquet

        table = pq.read_table(args.parquet, columns=["text"])
        rows = list(range(table.num_rows))
        random.Random(20261004).shuffle(rows)
        parts, size = [], 0
        for k in rows:
            t = clean(table.column(0)[k].as_py())
            parts.append(t)
            size += len(t) + 1
            if size >= args.chars:
                break
        text = "\n".join(parts)
        lm = CharLM(args.order)
        lm.train(text)
        lm.finish()
        with args.out.open("wb") as f:
            pickle.dump(lm, f, protocol=pickle.HIGHEST_PROTOCOL)
        contexts = [len(t) for t in lm.totals]
        print(f"trained on {len(text):,} characters, vocab {len(lm.vocab)}, contexts {contexts}")
    else:
        lm = load(args.lm)
        for a, b in [
            ("tarafından", "tarafindan"),
            ("ayrıca", "ayıca"),
            ("fıkrasında", "fikrasında"),
            ("Türkiye'de", "Türkiyede"),
            ("bir ev", "birev"),
            ("malî", "mali"),
        ]:
            sa = sum(lm.logprob(" " + a[:i], a[i]) for i in range(len(a)))
            sb = sum(lm.logprob(" " + b[:i], b[i]) for i in range(len(b)))
            print(f"{a:14} {sa:8.2f}   {b:14} {sb:8.2f}")


if __name__ == "__main__":
    main()
