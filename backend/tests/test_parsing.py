"""The light parser on documents built in code (tests/knowledge_samples.py)."""

from pathlib import Path

import pytest

from synapse.knowledge.filetypes import MediaType, detect
from synapse.knowledge.parsing import LightParser, ParseError, normalize
from synapse.knowledge.structure import Block, Table
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


STAMP = "BAKAN YARDIMCILIGI HUKUK HIZMETLERI GENEL MUDURLUGU 4.12.2024 10:19:24 E-11045126-010.06"


def test_a_scan_whose_text_layer_is_only_a_stamp_goes_to_ocr(tmp_path: Path) -> None:
    [stamped] = parse(tmp_path, samples.pdf(STAMP, picture=True)).pages
    assert (stamped.needs_ocr, stamped.issue) == (True, "no_text")
    # the same words without a picture under them are the page's own text
    [plain] = parse(tmp_path, samples.pdf(STAMP)).pages
    assert not plain.needs_ocr


def test_a_scan_with_a_text_layer_of_its_own_is_judged_by_its_words(tmp_path: Path) -> None:
    text = "\n".join(["Belediye meclisi karar defterine kayit edildi ve onaylandi."] * 6)
    [page] = parse(tmp_path, samples.pdf(text, picture=True)).pages
    assert not page.needs_ocr


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
        (samples.crowded_word(), MediaType.DOCX, "suspicious_package"),
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


def test_pages_carry_their_structure(tmp_path: Path) -> None:
    text_page, blank = parse(
        tmp_path, samples.pdf("Karar 2026/35 kabul edildi ve sunuldu.", "")
    ).pages
    assert text_page.blocks == (Block("paragraph", "Karar 2026/35 kabul edildi ve sunuldu.", 1),)
    assert blank.blocks == ()

    [word] = parse(tmp_path, samples.word()).pages
    assert word.blocks == (
        Block("heading", "Belediye Meclisi Kararı", 1, level=1),
        Block("paragraph", "Karar No: 2026/35. Meclis üyeleri toplandı.", 1),
        Block("heading", "Gündem", 1, level=2),
        Block("table", "", 1, table=Table((("Madde", "Karar"), ("1", "Kabul edildi")), 1)),
    )

    budget, empty = parse(tmp_path, samples.spreadsheet()).pages
    assert budget.blocks == (
        Block("heading", "Bütçe", 1, level=1),
        Block("table", "", 1, table=Table((("Kalem", "Tutar"), ("Personel", "1250000")), 1)),
    )
    assert empty.blocks == (Block("heading", "Boş", 2, level=1),)

    first, _ = parse(tmp_path, samples.slides()).pages
    assert first.blocks == (
        Block("heading", "KVKK Eğitimi", 1, level=2),
        Block("paragraph", "Açık rıza nedir?", 1),
        Block("paragraph", "Konuşmacı notu", 1),
    )


def test_a_merged_word_cell_keeps_its_text_once(tmp_path: Path) -> None:
    [page] = parse(tmp_path, samples.word_with_merged_cells()).pages
    [block] = page.blocks
    assert block.table == Table(
        (("Performans Göstergeleri", ""), ("P.G. 2.7.1.", "50"), ("", "20")), header_rows=1
    )


def test_title_and_note_rows_above_a_sheet_table_are_not_its_header(tmp_path: Path) -> None:
    [sheet] = parse(tmp_path, samples.spreadsheet_with_title()).pages
    assert sheet.blocks == (
        Block("heading", "Ücretler", 1, level=1),
        Block("paragraph", "BELEDİYE ÜCRET TARİFESİ", 1),
        Block("paragraph", "Fiyatlara KDV dahildir.", 1),
        Block("table", "", 1, table=Table((("Hizmet", "Ücret"), ("Nikah salonu", "1500")), 1)),
    )


def test_running_headers_and_footers_are_kept_once(tmp_path: Path) -> None:
    pages = [
        f"BELEDIYE MECLISI\nKarar {n} kabul edildi ve meclise sunuldu.\nSayfa {n} / 4"
        for n in range(1, 5)
    ]
    parsed = parse(tmp_path, samples.pdf(*pages)).pages
    # The header stays where it first appears; page numbers go; the decisions, which differ
    # only in their numbers, all stay.
    assert [[b.text for b in p.blocks] for p in parsed] == [
        ["BELEDIYE MECLISI Karar 1 kabul edildi ve meclise sunuldu."],
        ["Karar 2 kabul edildi ve meclise sunuldu."],
        ["Karar 3 kabul edildi ve meclise sunuldu."],
        ["Karar 4 kabul edildi ve meclise sunuldu."],
    ]
    # What the page shows is untouched.
    assert all("BELEDIYE MECLISI" in p.text and "Sayfa" in p.text for p in parsed)


def test_two_pages_have_no_running_lines(tmp_path: Path) -> None:
    parsed = parse(
        tmp_path, samples.pdf("BASLIK\nKarar 1 kabul edildi.", "BASLIK\nKarar 2 kabul edildi.")
    ).pages
    assert [p.blocks[0].text for p in parsed] == [
        "BASLIK Karar 1 kabul edildi.",
        "BASLIK Karar 2 kabul edildi.",
    ]
