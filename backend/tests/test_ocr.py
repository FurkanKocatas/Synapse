"""OCR without the engines: rendering, the identifier reading, and the text a page keeps."""

import io
from dataclasses import dataclass
from pathlib import Path

import pytest
from PIL import Image

from synapse.knowledge.headings import blocks_from_text
from synapse.knowledge.ocr import (
    OcrError,
    PageReading,
    TesseractEngine,
    TwoEngineReader,
    better_text,
    fix_lira,
    identifiers,
    prepare_image,
    render_pdf_page,
)
from synapse.knowledge.parsing import Page
from synapse.knowledge.processing import PageUpdate, page_update
from tests import knowledge_samples as samples
from tests.test_quality import CLEAN, GARBLED


@dataclass
class Fixed:
    """An engine that returns the same text for every image."""

    name: str
    text: str

    def recognize(self, image: Path) -> str:
        return self.text


def test_a_page_without_text_takes_the_ocr() -> None:
    page = Page(1, "page", "", issue="no_text")
    assert better_text(page, "Karar metni") == ("Karar metni", True)


def test_bad_ocr_in_the_file_is_replaced_by_good_ocr() -> None:
    page = Page(1, "page", GARBLED, issue="ocr_artefacts")
    assert better_text(page, CLEAN) == (CLEAN, True)


def test_a_good_text_layer_is_never_replaced_by_worse_ocr() -> None:
    # The quality check flagged this page by mistake; the OCR came out worse.
    page = Page(1, "page", CLEAN, issue="not_turkish_like")
    assert better_text(page, GARBLED) == (CLEAN, False)


def test_a_page_keeping_its_text_layer_keeps_no_ocr_identifiers() -> None:
    reading = PageReading(GARBLED, "engines", ("2026/36",), ("2026/35",))
    kept = page_update(Page(1, "page", CLEAN, issue="not_turkish_like"), reading)
    assert kept == PageUpdate(CLEAN, "layer", "engines", [], [], blocks=None)
    taken = page_update(Page(4, "page", "", issue="no_text"), reading)
    assert taken == PageUpdate(
        GARBLED,
        "ocr",
        "engines",
        ["2026/36"],
        ["2026/35"],
        blocks=[b.to_json() for b in blocks_from_text(GARBLED, 4)],
    )
    assert taken.blocks and taken.blocks[0]["page"] == 4


def test_a_page_without_a_scan_renders_at_300_dpi(tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(samples.pdf("Karar 2026/35", "ikinci sayfa"))
    image = render_pdf_page(pdf, 2, tmp_path)
    with Image.open(image) as picture:
        assert picture.mode == "L"
        # A letter-size page (612 points wide) at 300 dpi.
        assert picture.width == round(612 / 72 * 300)


def test_a_scan_renders_at_its_own_resolution_not_enlarged(tmp_path: Path) -> None:
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(samples.scanned_pdf("Karar 2026/35", dpi=200))
    with Image.open(render_pdf_page(pdf, 1, tmp_path)) as picture:
        # 200 dpi within PDFium's rounding of the page size; 300 dpi would be 2481.
        assert abs(picture.width - 8.27 * 200) <= 1


def test_an_image_keeps_its_resolution(tmp_path: Path) -> None:
    source = tmp_path / "scan.jpg"
    buffer = io.BytesIO()
    Image.new("RGB", (1240, 1754), "white").save(buffer, format="JPEG")  # A4 at 150 dpi
    source.write_bytes(buffer.getvalue())
    with Image.open(prepare_image(source, tmp_path)) as picture:
        assert (picture.mode, picture.width) == ("L", 1240)


def test_engine_failures_are_reported_as_ocr_errors(tmp_path: Path) -> None:
    engine = TesseractEngine(tessdata_dir=tmp_path / "missing")
    assert engine.name == "tesseract-tur+eng"
    with pytest.raises(OcrError):
        engine.recognize(tmp_path / "no-such-image.png")


def test_a_pound_sign_before_a_digit_is_a_lira_sign() -> None:
    assert fix_lira("Maliyet £2.500.000 ve £ 12") == "Maliyet ₺2.500.000 ve £ 12"
    assert fix_lira("birim (£)") == "birim (£)"


def test_identifiers_are_numbers_dates_and_amounts() -> None:
    text = (
        "Karar 2026/35 ile 15.03.2025 tarihli (E-83913885) yazı; tutar ₺2.500.000, "
        "oran %40, sayfa 3, madde 5393. algoritma2 sü-\nresi 2024’te"
    )
    assert set(identifiers(text)) == {
        "2026/35",
        "15.03.2025",
        "E-83913885",
        "₺2.500.000",
        "5393",
        "2024'te",
    }


def test_the_second_reading_finds_extra_and_uncertain_identifiers(tmp_path: Path) -> None:
    reader = TwoEngineReader(
        Fixed("text", "Tutar £2.500.000, karar 2026/35 ve 2026/36."),
        Fixed("second", "Tutar $2.500.000 karar 2026/35 ve 2026/38"),
    )
    reading = reader.read(tmp_path / "page.png")
    assert reading.text == "Tutar ₺2.500.000, karar 2026/35 ve 2026/36."
    assert reading.engine == "text+second"
    assert reading.extra_identifiers == ("$2.500.000", "2026/38")
    assert reading.uncertain_identifiers == ("2026/36", "₺2.500.000")
    reader.close()  # engines without close() are fine
