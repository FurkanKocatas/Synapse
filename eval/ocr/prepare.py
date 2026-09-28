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

It also renders the real scanned pages that have a hand-verified transcription in
eval/ocr/real/ (``doc-001-p0003.txt`` is page 3 of doc-001), grey, at the resolution of the
scan embedded in the page, so the OCR engine sees the scanner's pixels and nothing resampled.

Usage (from the repository root):
    uv run --directory backend python ../eval/ocr/prepare.py
Writes eval/ocr/work/ (git-ignored): images/, truth/, pages.json and real/.
"""

import csv
import io
import json
import random
import re
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageFilter
from synapse.knowledge.filetypes import MediaType
from synapse.knowledge.parsing import LightParser
from synapse.knowledge.quality import assess

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "eval" / "corpus"
WORK = Path(__file__).resolve().parent / "work"
REAL_TRUTH = Path(__file__).resolve().parent / "real"
REAL_NAME = re.compile(r"(doc-\d{3})-p(\d{4})")
FALLBACK_SCAN_DPI = 200  # a page without an embedded image; the corpus's usual scan resolution
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


def render_real() -> None:
    truths = sorted(REAL_TRUTH.glob("*.txt"))
    # A run that finds nothing would leave the real-scan table empty without saying why.
    if not truths:
        raise SystemExit(f"no hand-verified transcriptions in {REAL_TRUTH}")
    (WORK / "real").mkdir(parents=True, exist_ok=True)
    for truth in truths:
        match = REAL_NAME.fullmatch(truth.stem)
        if not match:
            raise SystemExit(f"{truth.name}: expected a name like doc-001-p0003.txt")
        document_id, number = match.group(1), int(match.group(2))
        document = pdfium.PdfDocument(CORPUS / "files" / f"{document_id}.pdf")
        page = document[number - 1]
        scans = [o for o in page.get_objects() if o.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE]
        width_points, _ = page.get_size()
        dpi = FALLBACK_SCAN_DPI
        if scans:
            dpi = round(scans[0].get_px_size()[0] / (width_points / 72))
        image = page.render(scale=dpi / 72).to_pil().convert("L")
        document.close()
        image.save(WORK / "real" / f"{truth.stem}.real.png")
        print(f"real scan {truth.stem}: {dpi} dpi, {image.width} x {image.height}")


def main() -> None:
    render_real()
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
