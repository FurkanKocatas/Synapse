"""OCR behind the ``OcrEngine`` port (ADR 0010, ingestion rule 4).

Pages that the page quality check sends to OCR are rendered to images and recognised. The
engine is chosen by benchmark (docs/benchmarks/ocr.md). Whatever the engine returns, the page
keeps whichever text is better: a text layer flagged by mistake is never replaced by worse OCR,
so a false alarm costs time only.

Runs only in workers (ADR 0002): rendering and recognising untrusted files.
"""

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pypdfium2 as pdfium
from PIL import Image

from synapse.knowledge import quality
from synapse.knowledge.parsing import PDFIUM_LOCK, Page

# Tesseract is trained on text about this resolution; lower-resolution images are enlarged.
TARGET_DPI = 300
MAX_DPI = 400
A4_WIDTH_INCHES = 8.27
OCR_TIMEOUT_SECONDS = 180


class OcrError(RuntimeError):
    """The engine failed on a page; the page keeps its original text."""


class OcrEngine(Protocol):
    name: str

    def recognize(self, image: Path) -> str: ...


@dataclass(frozen=True)
class TesseractEngine:
    tessdata_dir: Path | None = None
    languages: str = "tur"
    page_segmentation: int = 3
    name: str = "tesseract"

    def recognize(self, image: Path) -> str:
        command = [
            "tesseract",
            str(image),
            "-",
            "-l",
            self.languages,
            "--oem",
            "1",
            "--psm",
            str(self.page_segmentation),
        ]
        if self.tessdata_dir is not None:
            command += ["--tessdata-dir", str(self.tessdata_dir)]
        # One thread per page: the worker's concurrency decides how many pages run at once.
        environment = {**os.environ, "OMP_THREAD_LIMIT": "1"}
        try:
            result = subprocess.run(  # noqa: S603  (fixed program, file names we created)
                command,
                capture_output=True,
                text=True,
                check=True,
                timeout=OCR_TIMEOUT_SECONDS,
                env=environment,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
            raise OcrError(f"tesseract failed: {type(error).__name__}") from error
        return result.stdout


def render_pdf_page(pdf: Path, number: int, directory: Path) -> Path:
    """Render one PDF page to a grey PNG at the resolution OCR works best with.

    Scanned pages are one embedded image; their own resolution is used, enlarged to 300 dpi
    when lower and capped at 400.
    """
    with PDFIUM_LOCK:
        document = pdfium.PdfDocument(pdf)
        try:
            page = document[number - 1]
            width_points = page.get_width()
            native = _embedded_image_dpi(page, width_points)
            dpi = min(MAX_DPI, max(TARGET_DPI, native or TARGET_DPI))
            image = page.render(scale=dpi / 72, grayscale=True).to_pil()
            page.close()
        finally:
            document.close()
    target = directory / f"page-{number:05d}.png"
    image.save(target)
    return target


def prepare_image(source: Path, directory: Path) -> Path:
    """An uploaded image as a grey PNG, enlarged to 300 dpi (judged from A4 width) if smaller."""
    with Image.open(source) as picture:
        grey = picture.convert("L")
    dpi = grey.width / A4_WIDTH_INCHES
    if dpi < TARGET_DPI:
        factor = TARGET_DPI / dpi
        grey = grey.resize(
            (round(grey.width * factor), round(grey.height * factor)), Image.Resampling.LANCZOS
        )
    target = directory / "image.png"
    grey.save(target)
    return target


def _embedded_image_dpi(page: pdfium.PdfPage, width_points: float) -> float | None:
    widest = 0
    for obj in page.get_objects():
        if obj.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE:
            widest = max(widest, obj.get_px_size()[0])
    return widest / (width_points / 72) if widest else None


def better_text(original: Page, recognized: str) -> tuple[str, bool]:
    """The text the page should keep, and whether it is the OCR output."""
    if original.issue == "no_text":
        return recognized, True
    before = quality.assess(original.text)
    after = quality.assess(recognized)
    if before.needs_ocr and not after.needs_ocr:
        return recognized, True
    if after.needs_ocr and not before.needs_ocr:
        return original.text, False
    # Both judged alike: the one with fewer artefacts, then the more language-like one.
    if (after.artefacts, -after.char_score) < (before.artefacts, -before.char_score):
        return recognized, True
    return original.text, False


def temporary_directory() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory(prefix="synapse-ocr-")
