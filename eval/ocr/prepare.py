"""Prepare the OCR benchmark: page images with known text, from born-digital PDFs.

A born-digital page whose text layer passes the quality check has a known correct text, so it
can be rendered to an image and used to score OCR engines without hand labelling. Two images
per page:

- ``clean``: 300 dpi, as a good office scanner produces.
- ``scan``: 200 dpi, grey, slightly rotated, blurred and noisy, as a quick scan of a printout
  (the corpus's real municipal scans are 200 dpi).
- ``poor``: 150 dpi, black and white with speckles, saved as a low-quality JPEG and back: a
  fax-like copy, to see how each engine degrades.

Pages are drawn from every born-digital PDF (at most two per document, at least 400 letters,
the broken-encoding doc-083 left out), with a fixed seed so runs are comparable.

Usage (from the repository root):
    uv run --directory backend python ../eval/ocr/prepare.py
Writes eval/ocr/work/ (git-ignored): images/, truth/ and pages.json.
"""

import csv
import io
import json
import random
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageFilter
from synapse.knowledge.filetypes import MediaType
from synapse.knowledge.parsing import LightParser
from synapse.knowledge.quality import assess

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "eval" / "corpus"
WORK = Path(__file__).resolve().parent / "work"
PER_DOCUMENT = 2
MIN_LETTERS = 400
SEED = 20260928
BLACK_WHITE_THRESHOLD = 150
EXCLUDED = {"doc-083"}  # broken font encoding: its text layer is not a truth


def candidate_pages(row: dict[str, str]) -> list[tuple[int, str]]:
    parsed = LightParser().parse(CORPUS / "files" / f"{row['id']}.pdf", MediaType.PDF)
    found = []
    for page in parsed.pages:
        verdict = assess(page.text)
        if not page.needs_ocr and verdict.letters >= MIN_LETTERS:
            found.append((page.number, page.text))
    return found


def degrade(image: Image.Image, rng: random.Random) -> Image.Image:
    grey = image.convert("L")
    small = grey.resize((grey.width * 2 // 3, grey.height * 2 // 3), Image.Resampling.LANCZOS)
    tilted = small.rotate(rng.uniform(-0.8, 0.8), resample=Image.Resampling.BICUBIC, fillcolor=255)
    blurred = tilted.filter(ImageFilter.GaussianBlur(radius=0.6))
    return blurred.point(lambda v: max(0, min(255, v + rng.randint(-18, 18))))


def poor(image: Image.Image, rng: random.Random) -> Image.Image:
    grey = image.convert("L")
    small = grey.resize((grey.width // 2, grey.height // 2), Image.Resampling.BILINEAR)
    tilted = small.rotate(rng.uniform(-1.5, 1.5), resample=Image.Resampling.BICUBIC, fillcolor=255)
    speckled = tilted.point(lambda v: max(0, min(255, v + rng.randint(-40, 40))))
    bw = speckled.point(lambda v: 255 if v > BLACK_WHITE_THRESHOLD else 0)
    buffer = io.BytesIO()
    bw.convert("L").save(buffer, format="JPEG", quality=30)
    return Image.open(io.BytesIO(buffer.getvalue())).convert("L")


def main() -> None:
    rng = random.Random(SEED)
    with (CORPUS / "manifest.csv").open(encoding="utf-8") as handle:
        rows = [
            r
            for r in csv.DictReader(handle)
            if r["format"] == "PDF" and r["is_scanned"] == "no" and r["id"] not in EXCLUDED
        ]
    (WORK / "images").mkdir(parents=True, exist_ok=True)
    (WORK / "truth").mkdir(parents=True, exist_ok=True)
    pages = []
    for row in rows:
        candidates = candidate_pages(row)
        for number, text in rng.sample(candidates, min(PER_DOCUMENT, len(candidates))):
            name = f"{row['id']}-p{number:04d}"
            document = pdfium.PdfDocument(CORPUS / "files" / f"{row['id']}.pdf")
            image = document[number - 1].render(scale=300 / 72).to_pil()
            document.close()
            image.convert("RGB").save(WORK / "images" / f"{name}.clean.png")
            degrade(image, rng).save(WORK / "images" / f"{name}.scan.png")
            poor(image, rng).save(WORK / "images" / f"{name}.poor.png")
            (WORK / "truth" / f"{name}.txt").write_text(text, encoding="utf-8")
            pages.append({"name": name, "document": row["id"], "sector": row["sector"]})
    (WORK / "pages.json").write_text(json.dumps(pages, indent=1), encoding="utf-8")
    print(f"{len(pages)} pages from {len({p['document'] for p in pages})} documents -> {WORK}")


if __name__ == "__main__":
    main()
