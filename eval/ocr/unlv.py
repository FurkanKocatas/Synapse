"""The UNLV-ISRI English test sets (real scans, the sets Tesseract was measured on) laid out for
measure.py.

    python eval/ocr/unlv.py --archives DIR --work DIR

Each archive (bus, doe3, legal, mag, news, rep; 2B = 200 dpi binary, 3B = 300 dpi binary,
3A = 300 dpi adaptively thresholded) holds per page a TIFF scan, its zones (.uzn) and the text
of those zones (.txt). The truth is that text; the conditions are the scan's resolution and
binarisation. The truth covers the zones only (a figure page's truth is its caption), so each
image is written with everything outside its zones painted white: every engine, whole-page or
not, then reads what the truth holds.
"""

import argparse
import tarfile
from pathlib import Path

from PIL import Image

CONDITIONS = {"2B": "200dpi", "3B": "300dpi", "3A": "300dpi-adaptive"}
BOX_FIELDS = 4  # a zone line starts with left, top, width and height


def zones_only(tif: Path, target: Path) -> None:
    """The scan with everything outside its zones (.uzn: left top width height type) white."""
    with Image.open(tif) as scan:
        page = scan.convert("L")
        out = Image.new("L", page.size, 255)
        for line in tif.with_suffix(".uzn").read_text(encoding="latin-1").splitlines():
            parts = line.split()
            box_numbers = parts[:4]
            if len(box_numbers) == BOX_FIELDS and all(p.lstrip("-").isdigit() for p in box_numbers):
                left, top, width, height = map(int, box_numbers)
                box = (left, top, left + width, top + height)
                out.paste(page.crop(box), box[:2])
        out.save(target, optimize=True)


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("--archives", type=Path, required=True)
    options.add_argument("--work", type=Path, required=True)
    args = options.parse_args()
    raw = args.work / "raw"
    (args.work / "truth").mkdir(parents=True, exist_ok=True)
    (args.work / "images").mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for archive in sorted(args.archives.glob("*.tar.gz")):
        name, variant = archive.name.removesuffix(".tar.gz").split(".")
        if variant not in CONDITIONS:
            continue
        with tarfile.open(archive) as tar:
            tar.extractall(raw, filter="data")
        for tif in sorted((raw / f"{name}.{variant}").rglob(f"*.{variant}.tif")):
            text = tif.with_suffix(".txt")
            if not text.exists():
                continue
            stem = f"{name}-{tif.name.removesuffix(f'.{variant}.tif')}"
            truth = args.work / "truth" / f"{stem}.txt"
            if not truth.exists():
                truth.write_text(text.read_text(encoding="latin-1"), encoding="utf-8")
            image = args.work / "images" / f"{stem}.{CONDITIONS[variant]}.png"
            if not image.exists() and tif.with_suffix(".uzn").exists():
                zones_only(tif, image)
            counts[CONDITIONS[variant]] = counts.get(CONDITIONS[variant], 0) + 1
    print("laid out:", counts)


if __name__ == "__main__":
    main()
