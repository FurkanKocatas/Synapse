"""Line and word images with their text, read by a recogniser and scored (docs/research/ocr.md).

    python eval/ocr/lines.py layout --work DIR --ijdar DIR [--gold DIR] [--scu DIR]
    python eval/ocr/lines.py read --work DIR --engine tesseract [--tessdata /models/best]
    python eval/ocr/lines.py score --work DIR

``layout`` writes one list per subset, WORK/sets/<set>.<subset>.tsv ("image path<TAB>text"):
the IJDAR Turkish synthetic benchmark (CC BY 4.0: printed, handwritten and scene lines, Turkish
character confusions, distortions), its gold standard of 90 real photographs (Zenodo 21923181),
and the SCU-CENG Turkish receipts' cropped lines (MIT, phone photographs). All are test data.

``read`` writes WORK/out/<engine>/<set>.<subset>.tsv; ``score`` prints, per subset and engine,
words right (bag of words, as measure.py), lines exactly right and the character error rate.
"""

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

IJDAR_SUBSETS = (
    "text_category/printed",
    "text_category/handwritten",
    "text_category/scene",
    "turkish_char_confuse/turkish",
    "turkish_char_confuse/non_turkish",
    "distortions/clean",
    "distortions/blurry",
    "distortions/low_resolution",
    "distortions/noisy",
    "distortions/rotated",
)


def _write(work: Path, name: str, rows: list[tuple[Path, str]]) -> None:
    target = work / "sets" / f"{name}.tsv"
    target.parent.mkdir(parents=True, exist_ok=True)
    clean = [(p, " ".join(t.split())) for p, t in rows if t.strip() and p.exists()]
    target.write_text("".join(f"{p}\t{t}\n" for p, t in clean), encoding="utf-8")
    print(f"{name}: {len(clean)}")


def layout_ijdar(work: Path, root: Path) -> None:
    for subset in IJDAR_SUBSETS:
        labels = root / subset / "text_labels.txt"
        if not labels.exists():
            continue
        rows = []
        for line in labels.read_text(encoding="utf-8").splitlines():
            name, _, text = line.partition(" ")
            if name.endswith(".png"):
                rows.append((root / subset / name, text))
        _write(work, "ijdar." + subset.replace("/", "-"), rows)


def layout_gold(work: Path, root: Path) -> None:
    truth = json.loads((root / "ground_truth.json").read_text(encoding="utf-8"))
    paths = {p.name: p for p in root.rglob("*") if p.is_file() and p.name in truth}
    by_type: dict[str, list] = {}
    for name, entry in truth.items():
        if name in paths:
            by_type.setdefault(entry["type"], []).append((paths[name], entry["ground_truth"]))
    for kind, rows in sorted(by_type.items()):
        _write(work, f"gold.{kind}", rows)


def layout_scu(work: Path, root: Path) -> None:
    rows = [
        (p, p.with_suffix(".gt.txt").read_text(encoding="utf-8").strip())
        for p in sorted(root.rglob("*.tif"))
        if p.with_suffix(".gt.txt").exists()
    ]
    _write(work, "scu.lines", rows)


def tesseract(tessdata: str) -> object:
    os.environ["OMP_THREAD_LIMIT"] = "1"

    def one(path: str) -> str:
        command = [
            "tesseract",
            path,
            "-",
            "-l",
            "tur+eng",
            "--oem",
            "1",
            "--psm",
            "7",
            "--tessdata-dir",
            tessdata,
        ]
        # our own command over our own image paths
        return subprocess.run(command, capture_output=True, text=True, check=False).stdout  # noqa: S603

    def read(paths: list[str]) -> list[str]:
        with ThreadPoolExecutor(8) as pool:
            return list(pool.map(one, paths))

    return read


def read_all(work: Path, engine: str, tessdata: str) -> None:
    recognise = tesseract(tessdata)
    for listing in sorted((work / "sets").glob("*.tsv")):
        target = work / "out" / engine / listing.name
        if target.exists():
            continue
        rows = [line.split("\t", 1) for line in listing.read_text(encoding="utf-8").splitlines()]
        texts = recognise([p for p, _ in rows])  # type: ignore[operator]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "".join(f"{p}\t{' '.join(t.split())}\n" for (p, _), t in zip(rows, texts, strict=True)),
            encoding="utf-8",
        )
        print(engine, listing.stem, len(rows), flush=True)


def score(work: Path) -> None:
    # here, not at the top: ``read`` runs in the benchmark image, which has Tesseract only
    from measure import normalise, words  # noqa: PLC0415
    from rapidfuzz.distance import Levenshtein  # noqa: PLC0415

    print(f"{'set':42} {'engine':24} {'lines':>6} {'words':>7} {'exact':>7} {'cer':>7}")
    for listing in sorted((work / "sets").glob("*.tsv")):
        truth = dict(
            line.split("\t", 1) for line in listing.read_text(encoding="utf-8").splitlines()
        )
        for engine_dir in sorted((work / "out").iterdir()):
            path = engine_dir / listing.name
            if not path.exists():
                continue
            got = dict(
                line.split("\t", 1)
                for line in path.read_text(encoding="utf-8").splitlines()
                if "\t" in line
            )
            lost = total = exact = edits = chars = 0
            for image, text in truth.items():
                t, r = normalise(text), normalise(got.get(image, ""))
                tw, rw = Counter(words(t)), Counter(words(r))
                lost += max(sum((tw - rw).values()), sum((rw - tw).values()))
                total += sum(tw.values())
                exact += t.split() == r.split()
                edits += Levenshtein.distance(" ".join(t.split()), " ".join(r.split()))
                chars += len(" ".join(t.split()))
            right = 1 - lost / max(1, total)
            print(
                f"{listing.stem:42} {engine_dir.name:24} {len(truth):6} {right:7.4f} "
                f"{exact / len(truth):7.4f} {edits / max(1, chars):7.4f}"
            )


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = options.add_subparsers(dest="command", required=True)
    lay = sub.add_parser("layout")
    lay.add_argument("--work", type=Path, required=True)
    lay.add_argument("--ijdar", type=Path)
    lay.add_argument("--gold", type=Path)
    lay.add_argument("--scu", type=Path)
    rd = sub.add_parser("read")
    rd.add_argument("--work", type=Path, required=True)
    rd.add_argument("--engine", choices=("tesseract",), default="tesseract")
    rd.add_argument("--tessdata", default="/models/best")
    sc = sub.add_parser("score")
    sc.add_argument("--work", type=Path, required=True)
    args = options.parse_args()
    if args.command == "layout":
        if args.ijdar:
            layout_ijdar(args.work, args.ijdar)
        if args.gold:
            layout_gold(args.work, args.gold)
        if args.scu:
            layout_scu(args.work, args.scu)
    elif args.command == "read":
        read_all(args.work, "tesseract-best-tur+eng", args.tessdata)
    else:
        score(args.work)


if __name__ == "__main__":
    main()
