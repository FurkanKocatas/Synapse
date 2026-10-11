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

With ``--masked`` it writes the same pages, the same seed and the same degradations to
eval/ocr/work-masked/, with the truth made to match what the page shows (masks.py): every image
no text-layer character lies on is blanked first (a map's place names or a logo's words are
printed on the page and missing from its text layer, so the plain set counts an engine wrong for
reading them), and text that leaves no ink on the page (drawn invisibly, or white on white)
leaves the truth (the plain set counts an engine wrong for not reading what nobody can see).
pages.json then gives each page's blanked regions, their share of the page, and the words that
left the truth.

It also renders the real scanned pages that have a hand-verified transcription in
eval/ocr/real/ (``doc-001-p0003.txt`` is page 3 of doc-001), grey, at the resolution of the
scan embedded in the page, so the OCR engine sees the scanner's pixels and nothing resampled.

Usage (from the repository root):
    uv run --directory backend python ../eval/ocr/prepare.py
Writes eval/ocr/work/ (git-ignored): images/, truth/, pages.json and real/.
"""

import argparse
import csv
import io
import json
import random
import re
from pathlib import Path

import pypdfium2 as pdfium
from masks import seen_text, unread_regions
from PIL import Image, ImageDraw, ImageFilter
from synapse.knowledge.filetypes import MediaType
from synapse.knowledge.parsing import LightParser, normalize
from synapse.knowledge.quality import assess

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "eval" / "corpus"
WORK = Path(__file__).resolve().parent / "work"
WORK_MASKED = Path(__file__).resolve().parent / "work-masked"
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
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("--masked", action="store_true", help="the corrected set, to work-masked/")
    masked = options.parse_args().masked
    work = WORK_MASKED if masked else WORK
    if not masked:
        render_real()
    rng = random.Random(SEED)
    with (CORPUS / "manifest.csv").open(encoding="utf-8") as handle:
        rows = [
            r
            for r in csv.DictReader(handle)
            if r["format"] == "PDF" and r["is_scanned"] == "no" and r["id"] not in EXCLUDED
        ]
    (work / "images").mkdir(parents=True, exist_ok=True)
    (work / "truth").mkdir(parents=True, exist_ok=True)
    pages = []
    for row in rows:
        candidates = candidate_pages(row)
        for number, text in rng.sample(candidates, min(PER_DOCUMENT, len(candidates))):
            name = f"{row['id']}-p{number:04d}"
            document = pdfium.PdfDocument(CORPUS / "files" / f"{row['id']}.pdf")
            page = document[number - 1]
            image = page.render(scale=300 / 72).to_pil().convert("RGB")
            entry = {"name": name, "document": row["id"], "sector": row["sector"]}
            truth = text
            if masked:
                # The same random draws as the plain set: only the pixels differ.
                regions = unread_regions(page, 300 / 72)
                draw = ImageDraw.Draw(image)
                for box in regions:
                    draw.rectangle(box, fill="white")
                area = sum((right - left) * (bottom - top) for left, top, right, bottom in regions)
                entry["unread_regions"] = len(regions)
                entry["unread_share"] = round(area / (image.width * image.height), 4)
                truth = normalize(seen_text(page, image.convert("L"), 300 / 72))
                entry["unseen_words"] = len(text.split()) - len(truth.split())
            document.close()
            image.save(work / "images" / f"{name}.clean.png")
            degrade(image, rng).save(work / "images" / f"{name}.scan.png")
            poor(image, rng).save(work / "images" / f"{name}.poor.png")
            (work / "truth" / f"{name}.txt").write_text(truth, encoding="utf-8")
            pages.append(entry)
    (work / "pages.json").write_text(json.dumps(pages, indent=1), encoding="utf-8")
    print(f"{len(pages)} pages from {len({p['document'] for p in pages})} documents -> {work}")


if __name__ == "__main__":
    main()
