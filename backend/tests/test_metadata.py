"""A document's metadata: suggested from what it says about itself, checked as people set it."""

import datetime

import pytest

from synapse.knowledge.metadata import (
    HEAD_CHARS,
    InvalidMetadataError,
    Suggested,
    checked,
    suggest,
)


@pytest.mark.parametrize(
    ("title", "head", "kind"),
    [
        ("Personel Yönetmeliği", "", "Yönetmelik"),
        ("63_insan-kay", "T.C.\nBELEDİYE BAŞKANLIĞI\nPERSONEL YÖNETMELİĞİ", "Yönetmelik"),
        # at the same place the longer word: a decree is not a decision
        ("belge", "CUMHURBAŞKANLIĞI KARARNAMESİ", "Kararname"),
        ("belge", "MECLİS KARARI", "Karar"),
        ("Toplantı Tutanağı", "", "Tutanak"),
        # the title before the page, and on the page the earliest
        ("faaliyet-raporu", "Meclis kararı ile kabul edildi.", "Rapor"),
        ("belge", "Bu yönerge, meclis kararı ile yürürlüğe girer.", "Yönerge"),
        # a kind word inside another word is not one
        ("belge", "Mukarar ve istatistik", None),
        ("İçindekiler", "", None),
    ],
)
def test_the_kind_is_the_earliest_kind_word(title: str, head: str, kind: str | None) -> None:
    assert suggest(title, head).kind == kind


def test_the_date_and_number_come_from_the_head_of_the_first_page() -> None:
    head = "MECLİS KARARI\nKarar 2026/35 kabul edildi ve 15.03.2026 tarihinde sunuldu."
    assert suggest("belge", head) == Suggested("Karar", datetime.date(2026, 3, 15), "2026/35")
    late = "x" * HEAD_CHARS + " Karar 2026/35, 15.03.2026"
    assert suggest("belge", late) == Suggested(None, None, None)


def test_changes_are_stored_trimmed_and_in_order() -> None:
    stored = checked(
        {
            "reference": "  ",
            "tags": [" imar ", "imar", "", "bütçe  planı"],
            "title": "  Meclis   kararı ",
            "document_date": None,
        }
    )
    assert list(stored.items()) == [
        ("title", "Meclis kararı"),
        ("tags", ["imar", "bütçe planı"]),
        ("document_date", None),
        ("reference", None),
    ]
    assert checked({"document_date": datetime.date(2026, 3, 15)}) == {
        "document_date": datetime.date(2026, 3, 15)
    }


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"owner": "x"},
        {"title": None},
        {"title": "   "},
        {"title": "x" * 501},
        {"kind": 3},
        {"document_date": "2026-03-15"},
        {"tags": "imar"},
        {"tags": [str(i) for i in range(21)]},
        {"tags": ["x" * 51]},
    ],
)
def test_wrong_changes_are_refused(changes: dict[str, object]) -> None:
    with pytest.raises(InvalidMetadataError):
        checked(changes)
