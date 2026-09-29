"""Typed entities and duplicate fingerprints (knowledge/entities.py, knowledge/dedup.py)."""

import pytest

from synapse.knowledge.dedup import content_hash, distance, simhash
from synapse.knowledge.entities import extract


def found(text: str) -> list[tuple[str, str, str]]:
    return [(e.kind, e.text, e.value) for e in extract(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("15.03.2025 tarihli yazı", [("date", "15.03.2025", "2025-03-15")]),
        ("Kabul Tarihi : 3/7/2005", [("date", "3/7/2005", "2005-07-03")]),
        ("3 Temmuz 2005 günü", [("date", "3 Temmuz 2005", "2005-07-03")]),
        ("Meclisin 2026/35 sayılı kararı", [("decision_number", "2026/35", "2026/35")]),
        ("Karar No: 123 ile", [("decision_number", "Karar No: 123", "123")]),
        # Two rules match here; the span is claimed once, by the rule listed first.
        ("Karar No: 2026/35", [("decision_number", "Karar No: 2026/35", "2026/35")]),
        (
            "E.2023/123 K.2024/45",
            [
                ("decision_number", "E.2023/123", "E.2023/123"),
                ("decision_number", "K.2024/45", "K.2024/45"),
            ],
        ),
        ("5393 sayılı Belediye Kanunu", [("law_number", "5393 sayılı", "5393")]),
        ("Madde 15 uyarınca", [("article", "Madde 15", "15")]),
        ("md. 7 kapsamında", [("article", "md. 7", "7")]),
        ("Kanunun 18 inci maddesi", [("article", "18 inci madde", "18")]),
        ("Maliyet ₺2.500.000", [("amount", "₺2.500.000", "2500000.00 TRY")]),
        ("1.000.000,00 TL.", [("amount", "1.000.000,00 TL", "1000000.00 TRY")]),
        (
            "tutar 12.500 TL ve 300 dolar",
            [
                ("amount", "12.500 TL", "12500.00 TRY"),
                ("amount", "300 dolar", "300.00 USD"),
            ],
        ),
        ("123 ada 4 parsel", [("parcel", "123 ada 4 parsel", "123/4")]),
        ("4.679 Ada,1 Parsel", [("parcel", "4.679 Ada,1 Parsel", "4679/1")]),
        (
            "E.: 2009/34, K.: 2010/72",
            [
                ("decision_number", "E.: 2009/34", "E.2009/34"),
                ("decision_number", "K.: 2010/72", "K.2010/72"),
            ],
        ),
        ("Ada: 45, Parsel: 6", [("parcel", "Ada: 45, Parsel: 6", "45/6")]),
    ],
)
def test_entities_are_found_and_normalised(text: str, expected: list[tuple[str, str, str]]) -> None:
    assert found(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "31.02.2025 geçersiz bir tarih",  # no such day
        "3 maddelik bir liste",
        "toplam 12500 kişi",  # a number without a currency
        "sayfa 3 ve 4",
        "5393 kişi katıldı",
    ],
)
def test_no_entity_where_there_is_none(text: str) -> None:
    assert found(text) == []


def test_offsets_point_into_the_original_text() -> None:
    text = "İLGİ: 12.01.2026 tarihli ve 2026/4 sayılı yazı."
    for entity in extract(text):
        assert text[entity.start : entity.start + len(entity.text)] == entity.text


def test_case_and_spacing_do_not_change_the_content_hash() -> None:
    assert content_hash("Belediye  Meclisi\nkararı") == content_hash("BELEDİYE meclisi KARARI")
    assert content_hash("karar 1") != content_hash("karar 2")


def test_near_duplicates_have_close_simhashes() -> None:
    decision = (
        "Belediye Meclisinin 01.07.2026 tarihli oturumunda Zabıta Müdürlüğünün özel servis "
        "araçları öğrenci taşıma ücret tarifesi konulu yazısı komisyona havale edilmiş olup "
        "tarifenin yüzde kırk oranında artırılmasına oy birliği ile karar verilmiştir."
    )
    reissued = decision.replace("01.07.2026", "08.07.2026")
    unrelated = (
        "Hastanede enfeksiyon kontrol komitesi her ay toplanır ve el hijyeni uyum oranlarını "
        "birimlere göre raporlar; sonuçlar kalite birimine iletilir ve arşivlenir."
    )
    assert distance(simhash(decision), simhash(reissued)) <= 10
    assert distance(simhash(decision), simhash(unrelated)) >= 20
    assert -(2**63) <= simhash(decision) < 2**63
