"""OCR behind the ``PageReader`` port (ADR 0010, ingestion rule 4).

Pages that the page quality check sends to OCR are rendered to images and read by two engines,
as measured in docs/benchmarks/ocr.md ("Two engines together"):

- Tesseract (the "best" models, Turkish and English) gives the text. English adds the symbols
  the Turkish model cannot write ("%", "+", "="); neither has "₺", which Tesseract reads as "£".
- RapidOCR reads the page again, and only its identifiers are used: dates, decision numbers,
  amounts. Those Tesseract lacks are kept as search terms, never as text a reader or a model
  sees (two in five of them are wrong). Tesseract's identifiers that RapidOCR did not read are
  marked uncertain, so an answer can flag them: in the benchmark an identifier both engines
  read was right 98 to 99% of the time, one only Tesseract read about half the time.

Whatever the engines return, the page keeps whichever text is better: a text layer flagged by
mistake is never replaced by worse OCR, so a false alarm costs time only.

Runs only in workers (ADR 0002): rendering and recognising untrusted files.
"""

import os
import re
import subprocess
import tempfile
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pypdfium2 as pdfium
from PIL import Image

from synapse.knowledge import quality
from synapse.knowledge.parsing import PDFIUM_LOCK, Page, normalize

# The engines read scans at their own resolution: enlarging to 300 dpi first made identifiers
# worse in the benchmark (a ministry circular fell from 0.80 to 0.30).
FALLBACK_DPI = 300  # a page with no embedded scan, such as a broken text layer
MAX_DPI = 600  # bounds memory for unusually fine scans
OCR_TIMEOUT_SECONDS = 180
TESSERACT_LANGUAGES = "tur+eng"

# Identifiers as the benchmark defines them (eval/ocr/score.py): at least four characters, at
# least half of the letters and digits are digits.
MIN_IDENTIFIER_LENGTH = 4
_EDGE = "()[]{}<>\"'«»“”‘’.,;:!?*•"
# Typographic apostrophes and dashes become ASCII, as search will treat them.
_APOSTROPHES = {chr(c): "'" for c in (0x2019, 0x2018, 0x60, 0xB4)}
_DASHES = {chr(c): "-" for c in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2212)}
_TYPOGRAPHY = str.maketrans(_APOSTROPHES | _DASHES)
_HYPHENATED = re.compile(r"-\n(?=\w)")
# Tesseract reads "₺" as "£". The pound sign occurs nowhere in the evaluation corpus's text
# layers (the lira sign 650 times), and every "£" before a digit in the benchmark was a "₺".
_POUND_BEFORE_DIGIT = re.compile(r"£(?=\d)")


class OcrError(RuntimeError):
    """An engine failed on a page; the page keeps its original text."""


class TextEngine(Protocol):
    @property
    def name(self) -> str: ...

    def recognize(self, image: Path) -> str: ...


@dataclass(frozen=True)
class PageReading:
    text: str
    engine: str
    # Identifiers the second engine read that the text lacks: search terms only.
    extra_identifiers: tuple[str, ...]
    # Identifiers in the text that the second engine did not read: flag them in answers.
    uncertain_identifiers: tuple[str, ...]


class PageReader(Protocol):
    @property
    def name(self) -> str: ...

    def read(self, image: Path) -> PageReading: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class TesseractEngine:
    tessdata_dir: Path | None = None
    languages: str = TESSERACT_LANGUAGES
    page_segmentation: int = 3

    @property
    def name(self) -> str:
        return f"tesseract-{self.languages}"

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


@dataclass
class TwoEngineReader:
    """Tesseract for the text, a second engine for a second reading of the identifiers."""

    text_engine: TextEngine
    second_engine: TextEngine

    @property
    def name(self) -> str:
        return f"{self.text_engine.name}+{self.second_engine.name}"

    def read(self, image: Path) -> PageReading:
        text = self.text_engine.recognize(image)
        return two_readings(text, self.second_engine.recognize(image), self.name)

    def close(self) -> None:
        for engine in (self.text_engine, self.second_engine):
            close = getattr(engine, "close", None)
            if close is not None:
                close()


def two_readings(text: str, second: str, engine: str) -> PageReading:
    """The page's text, with the identifiers a second reading adds (search terms only) and those
    it does not confirm (to flag in answers)."""
    text = normalize(fix_lira(text))
    first = identifiers(text)
    other = identifiers(second)
    return PageReading(
        text=text,
        engine=engine,
        extra_identifiers=tuple(sorted(other - first)),
        uncertain_identifiers=tuple(sorted(first - other)),
    )


def fix_lira(text: str) -> str:
    return _POUND_BEFORE_DIGIT.sub("₺", text)


def identifiers(text: str) -> Counter[str]:
    text = _HYPHENATED.sub("", unicodedata.normalize("NFC", text).translate(_TYPOGRAPHY))
    found: Counter[str] = Counter()
    for word in text.split():
        token = word.strip(_EDGE)
        alnum = [ch for ch in token if ch.isalnum()]
        digits = sum(ch.isdigit() for ch in alnum)
        if len(token) >= MIN_IDENTIFIER_LENGTH and digits and digits * 2 >= len(alnum):
            found[token] += 1
    return found


def render_pdf_page(pdf: Path, number: int, directory: Path) -> Path:
    """Render one PDF page to a grey PNG for OCR.

    A scanned page is one embedded image, rendered at that image's own resolution (at most
    600 dpi); a page without one at 300 dpi.
    """
    with PDFIUM_LOCK:
        document = pdfium.PdfDocument(pdf)
        try:
            page = document[number - 1]
            native = _embedded_image_dpi(page, page.get_width())
            dpi = min(MAX_DPI, round(native)) if native else FALLBACK_DPI
            image = page.render(scale=dpi / 72, grayscale=True).to_pil()
            page.close()
        finally:
            document.close()
    target = directory / f"page-{number:05d}.png"
    image.save(target)
    return target


def prepare_image(source: Path, directory: Path) -> Path:
    """An uploaded image as a grey PNG, at its own resolution (the first frame of a TIFF)."""
    with Image.open(source) as picture:
        grey = picture.convert("L")
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
