"""Text extraction behind the ``Parser`` port (ADR 0010, phase 4 step 3).

``LightParser`` reads born-digital files with small libraries: PDF text layers with PDFium,
Word, Excel and PowerPoint files with their Python readers. It keeps the unit a citation needs
(page, slide, sheet) and marks pages without usable text for OCR. Layout analysis and OCR come
in step 4, behind the same port, chosen by benchmark.

Runs only in workers, never in the API process (ADR 0002): these files are untrusted.
"""

import threading
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

import docx
import openpyxl
import pptx
import pypdfium2 as pdfium
from docx.table import Table
from docx.text.paragraph import Paragraph

from synapse.knowledge.filetypes import MediaType

PageKind = Literal["page", "slide", "sheet", "document"]

# Fewer visible characters than this on a PDF page means the text layer is missing (a scan)
# or unusable; the page goes to OCR.
MIN_TEXT_CHARS = 20
MAX_PAGES = 5000
MAX_SHEET_CELLS = 500_000
# Office files are zip packages; refuse ones that expand to far more than they weigh.
MAX_UNCOMPRESSED_BYTES = 1 << 30
MAX_COMPRESSION_RATIO = 200

# PDFium is not thread-safe, and the worker parses in threads.
_PDFIUM = threading.Lock()


@dataclass(frozen=True)
class Page:
    number: int
    kind: PageKind
    text: str
    needs_ocr: bool = False
    label: str | None = None


@dataclass(frozen=True)
class Parsed:
    pages: list[Page]


class ParseError(ValueError):
    """The file cannot be read; ``reason`` is a stable code shown to editors."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Parser(Protocol):
    def parse(self, path: Path, media_type: MediaType) -> Parsed: ...


def normalize(text: str) -> str:
    """NFC, Unix line ends, no NUL or other control characters except newline and tab."""
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    return "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C").strip()


def visible_chars(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


class LightParser:
    def parse(self, path: Path, media_type: MediaType) -> Parsed:
        match media_type:
            case MediaType.PDF:
                return _pdf(path)
            case MediaType.DOCX:
                _check_package(path)
                return _docx(path)
            case MediaType.XLSX:
                _check_package(path)
                return _xlsx(path)
            case MediaType.PPTX:
                _check_package(path)
                return _pptx(path)
            case MediaType.PNG | MediaType.JPEG | MediaType.TIFF:
                # An image is one page with no text layer.
                return Parsed([Page(1, "page", "", needs_ocr=True)])


def _pdf(path: Path) -> Parsed:
    with _PDFIUM:
        try:
            document = pdfium.PdfDocument(path)
        except pdfium.PdfiumError as error:
            reason = "encrypted" if "password" in str(error).lower() else "unreadable"
            raise ParseError(reason) from error
        try:
            if len(document) > MAX_PAGES:
                raise ParseError("too_many_pages")
            pages = []
            for index in range(len(document)):
                page = document[index]
                textpage = page.get_textpage()
                text = normalize(textpage.get_text_range())
                textpage.close()
                page.close()
                pages.append(
                    Page(index + 1, "page", text, needs_ocr=visible_chars(text) < MIN_TEXT_CHARS)
                )
        finally:
            document.close()
    if not pages:
        raise ParseError("empty")
    return Parsed(pages)


def _check_package(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as package:
            entries = package.infolist()
    except zipfile.BadZipFile as error:
        raise ParseError("unreadable") from error
    expanded = sum(entry.file_size for entry in entries)
    compressed = max(1, sum(entry.compress_size for entry in entries))
    if expanded > MAX_UNCOMPRESSED_BYTES or expanded / compressed > MAX_COMPRESSION_RATIO:
        raise ParseError("suspicious_package")


def _docx(path: Path) -> Parsed:
    try:
        document = docx.Document(str(path))
    except Exception as error:  # python-docx raises many kinds for a broken package
        raise ParseError("unreadable") from error
    lines: list[str] = []
    # Paragraphs and tables in document order, headings marked so chunking can follow them.
    for block in document.iter_inner_content():
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if not text:
                continue
            level = _heading_level(block)
            lines.append(f"{'#' * level} {text}" if level else text)
        elif isinstance(block, Table):
            lines.extend(_table_lines(block))
    return Parsed([Page(1, "document", normalize("\n".join(lines)))])


def _heading_level(paragraph: Paragraph) -> int:
    name = (paragraph.style.name if paragraph.style is not None else "") or ""
    # "Heading 2" in English templates, "Ba\u015fl\u0131k 2" in Turkish ones.
    for prefix in ("Heading ", "Ba\u015fl\u0131k "):
        if name.startswith(prefix) and name[len(prefix) :].isdigit():
            return min(int(name[len(prefix) :]), 6)
    return 1 if name == "Title" else 0


def _table_lines(table: Table) -> list[str]:
    lines = []
    for row in table.rows:
        cells = [" ".join(cell.text.split()) for cell in row.cells]
        # Merged cells repeat; keep each distinct value once, in order.
        deduped = [c for i, c in enumerate(cells) if c and (i == 0 or c != cells[i - 1])]
        if deduped:
            lines.append(" | ".join(deduped))
    return lines


def _xlsx(path: Path) -> Parsed:
    # Opened through a handle: given a path, openpyxl insists on an .xlsx name, and blobs are
    # stored under their hash.
    handle = path.open("rb")
    try:
        workbook = openpyxl.load_workbook(handle, read_only=True, data_only=True)
    except Exception as error:  # openpyxl raises many kinds for a broken package
        handle.close()
        raise ParseError("unreadable") from error
    pages = []
    try:
        for number, sheet in enumerate(workbook.worksheets, start=1):
            lines, cells = [], 0
            for row in sheet.iter_rows(values_only=True):
                cells += len(row)
                if cells > MAX_SHEET_CELLS:
                    raise ParseError("sheet_too_large")
                values = ["" if value is None else str(value).strip() for value in row]
                if any(values):
                    lines.append("\t".join(values).rstrip("\t"))
            pages.append(Page(number, "sheet", normalize("\n".join(lines)), label=sheet.title))
    finally:
        workbook.close()
        handle.close()
    return Parsed(pages)


def _pptx(path: Path) -> Parsed:
    try:
        presentation = pptx.Presentation(str(path))
    except Exception as error:  # python-pptx raises many kinds for a broken package
        raise ParseError("unreadable") from error
    pages = []
    for number, slide in enumerate(presentation.slides, start=1):
        lines: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                lines.extend(p.strip() for p in shape.text_frame.text.split("\n") if p.strip())
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    cells = [" ".join(cell.text.split()) for cell in row.cells]
                    if any(cells):
                        lines.append(" | ".join(cells))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                lines.append(notes)
        pages.append(Page(number, "slide", normalize("\n".join(lines))))
    return Parsed(pages)
