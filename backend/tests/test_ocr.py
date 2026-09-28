"""OCR helpers that do not need the engine: rendering, and choosing the text a page keeps."""

import io
from pathlib import Path

import pytest
from PIL import Image

from synapse.knowledge.ocr import (
    OcrError,
    TesseractEngine,
    better_text,
    prepare_image,
    render_pdf_page,
)
from synapse.knowledge.parsing import Page
from tests import knowledge_samples as samples
from tests.test_quality import CLEAN, GARBLED


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


def test_pdf_pages_render_at_ocr_resolution(tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(samples.pdf("Karar 2026/35", "ikinci sayfa"))
    image = render_pdf_page(pdf, 2, tmp_path)
    with Image.open(image) as picture:
        assert picture.mode == "L"
        # A letter-size page (612 points wide) at 300 dpi.
        assert picture.width == round(612 / 72 * 300)


def test_small_images_are_enlarged_to_300_dpi(tmp_path: Path) -> None:
    source = tmp_path / "scan.jpg"
    buffer = io.BytesIO()
    Image.new("RGB", (1240, 1754), "white").save(buffer, format="JPEG")  # A4 at 150 dpi
    source.write_bytes(buffer.getvalue())
    with Image.open(prepare_image(source, tmp_path)) as picture:
        assert picture.mode == "L"
        assert abs(picture.width / 8.27 - 300) < 2


def test_engine_failures_are_reported_as_ocr_errors(tmp_path: Path) -> None:
    engine = TesseractEngine(tessdata_dir=tmp_path / "missing")
    with pytest.raises(OcrError):
        engine.recognize(tmp_path / "no-such-image.png")
