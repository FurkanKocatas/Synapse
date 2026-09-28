"""The light parser on documents built in code (tests/knowledge_samples.py)."""

from pathlib import Path

import pytest

from synapse.knowledge.filetypes import MediaType, detect
from synapse.knowledge.parsing import LightParser, ParseError, normalize
from tests import knowledge_samples as samples


def parse(tmp_path: Path, data: bytes):  # type: ignore[no-untyped-def]
    path = tmp_path / "sample"
    path.write_bytes(data)
    return LightParser().parse(path, detect(path))


def test_pdf_pages_keep_their_numbers_and_blank_pages_go_to_ocr(tmp_path: Path) -> None:
    parsed = parse(tmp_path, samples.pdf("Karar 2026/35 kabul edildi ve meclise sunuldu.", ""))
    first, second = parsed.pages
    assert (first.number, first.kind, first.needs_ocr) == (1, "page", False)
    assert "Karar 2026/35" in first.text
    assert (second.number, second.text, second.needs_ocr) == (2, "", True)


def test_word_keeps_headings_and_tables_in_order(tmp_path: Path) -> None:
    [page] = parse(tmp_path, samples.word()).pages
    assert page.kind == "document"
    assert page.text.splitlines() == [
        "# Belediye Meclisi Kararı",
        "Karar No: 2026/35. Meclis üyeleri toplandı.",
        "## Gündem",
        "Madde | Karar",
        "1 | Kabul edildi",
    ]


def test_spreadsheets_become_one_unit_per_sheet(tmp_path: Path) -> None:
    budget, empty = parse(tmp_path, samples.spreadsheet()).pages
    assert (budget.kind, budget.label, budget.number) == ("sheet", "Bütçe", 1)
    assert budget.text.splitlines() == ["Kalem\tTutar", "Personel\t1250000"]
    assert (empty.label, empty.text) == ("Boş", "")


def test_slides_include_their_notes(tmp_path: Path) -> None:
    first, second = parse(tmp_path, samples.slides()).pages
    assert first.kind == "slide"
    assert first.text.splitlines() == ["KVKK Eğitimi", "Açık rıza nedir?", "Konuşmacı notu"]
    assert (second.number, second.text) == (2, "")


def test_images_are_one_page_for_ocr(tmp_path: Path) -> None:
    path = tmp_path / "scan.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    [page] = LightParser().parse(path, MediaType.PNG).pages
    assert page.needs_ocr


@pytest.mark.parametrize(
    ("data", "media_type", "reason"),
    [
        (b"%PDF-1.7\nnothing that pdfium can read", MediaType.PDF, "unreadable"),
        (samples.zip_bomb_word(), MediaType.DOCX, "suspicious_package"),
        (b"PK\x03\x04broken", MediaType.XLSX, "unreadable"),
    ],
)
def test_unreadable_files_fail_with_a_reason(
    tmp_path: Path, data: bytes, media_type: MediaType, reason: str
) -> None:
    path = tmp_path / "bad"
    path.write_bytes(data)
    with pytest.raises(ParseError) as failed:
        LightParser().parse(path, media_type)
    assert failed.value.reason == reason


def test_text_is_normalized() -> None:
    decomposed = "Kararı şube\r\nA\x00B\x07\tC"  # "ş" as s + combining cedilla
    assert normalize(decomposed) == "Kararı şube\nAB\tC"
