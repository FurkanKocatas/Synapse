"""Section levels from Turkish document conventions (knowledge/headings.py)."""

import pytest

from synapse.knowledge.chunking import split_text
from synapse.knowledge.headings import Section, blocks_from_text, section
from synapse.knowledge.structure import Block

EN_DASH = chr(0x2013)


@pytest.mark.parametrize(
    ("line", "marked", "expected"),
    [
        ("BİRİNCİ KISIM", False, Section(1, "BİRİNCİ KISIM")),
        ("İkinci Bölüm", False, Section(2, "İkinci Bölüm")),
        ("ON BİRİNCİ BÖLÜM Mali Hükümler", True, Section(2, "ON BİRİNCİ BÖLÜM Mali Hükümler")),
        (
            f"MADDE 5 {EN_DASH} (1) Bu Yönetmeliğin amacı ...",
            False,
            Section(3, "MADDE 5", running=True),
        ),
        ("Madde 2- Bu Kanun belediyeleri kapsar.", False, Section(3, "Madde 2", running=True)),
        ("Geçici Madde 3- Yürürlük.", False, Section(3, "Geçici Madde 3", running=True)),
        ("9. MALİ YÖNETİM", False, Section(2, "9. MALİ YÖNETİM")),
        ("3.2.1. HEDEFLER", False, Section(4, "3.2.1. HEDEFLER")),
        (
            "B. Temel Politikalar ve Öncelikler",
            True,
            Section(2, "B. Temel Politikalar ve Öncelikler"),
        ),
        ("Hedefler:", True, Section(3, "Hedefler:")),
        # Running text that looks numbered is not a heading.
        ("1. Uygun mülkiyet bulunamaması", False, None),
        ("3. Maliyet analizi yapılması", False, None),
        ("Birinci bölümde anlatıldığı gibi, bu karar uygulanır.", False, None),
        ("Bu madde 5 inci fıkraya göre uygulanır.", False, None),
    ],
)
def test_section_levels(line: str, marked: bool, expected: Section | None) -> None:
    assert section(line, marked=marked) == expected


def test_sentences_do_not_end_at_abbreviations_or_initials() -> None:
    text = (
        "Başvuru md. 5 uyarınca yapılır. Dr. A. Yılmaz vb. kişiler katılır. "
        "Sonuç 2026 yılında açıklanır. bu cümle küçük harfle devam eder."
    )
    pieces = split_text(text, max_tokens=6, count=lambda t: len(t.split()))
    assert pieces[0] == "Başvuru md. 5 uyarınca yapılır."
    assert pieces[1].startswith("Dr. A. Yılmaz vb. kişiler")
    assert " ".join(pieces).split() == text.split()


LAW_PAGE = """BELEDİYE KANUNU
BİRİNCİ KISIM
Genel Hükümler
BİRİNCİ BÖLÜM
Amaç, Kapsam ve Tanımlar
Amaç
Madde 1- Bu Kanunun amacı; belediyenin kuruluşu, organları, yönetimi, görev, yetki
ve sorumlulukları ile çalışma usul ve esaslarını düzenlemektir.
Kapsam
Madde 2- Bu Kanun belediyeleri kapsar. Belediye sınırları içinde uygulanan sü-
reler ayrıca belirlenir.
9. MALİ YÖNETİM
1. Uygun mülkiyet bulunamaması
2. İmar planının uygun olmaması"""


def test_a_text_layer_becomes_headings_articles_and_paragraphs() -> None:
    assert blocks_from_text(LAW_PAGE, 7) == [
        Block("paragraph", "BELEDİYE KANUNU", 7),
        Block("heading", "BİRİNCİ KISIM Genel Hükümler", 7, level=1),
        Block("heading", "BİRİNCİ BÖLÜM Amaç, Kapsam ve Tanımlar", 7, level=2),
        Block("paragraph", "Amaç", 7),
        Block(
            "paragraph",
            "Madde 1- Bu Kanunun amacı; belediyenin kuruluşu, organları, yönetimi, görev, yetki "
            "ve sorumlulukları ile çalışma usul ve esaslarını düzenlemektir.",
            7,
            level=3,
            label="Madde 1",
        ),
        Block("paragraph", "Kapsam", 7),
        Block(
            "paragraph",
            "Madde 2- Bu Kanun belediyeleri kapsar. Belediye sınırları içinde uygulanan süreler "
            "ayrıca belirlenir.",
            7,
            level=3,
            label="Madde 2",
        ),
        Block("heading", "9. MALİ YÖNETİM", 7, level=2),
        Block("list_item", "1. Uygun mülkiyet bulunamaması", 7),
        Block("list_item", "2. İmar planının uygun olmaması", 7),
    ]


def test_a_title_below_a_long_heading_is_not_taken_into_it() -> None:
    blocks = blocks_from_text("BİRİNCİ BÖLÜM Amaç ve Kapsam Hükümleri\nGenel Esaslar", 1)
    assert [b.kind for b in blocks] == ["heading", "paragraph"]
