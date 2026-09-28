"""The per-page Turkish quality check on hand-written examples of each case it must tell apart."""

import pytest

from synapse.knowledge import turkish
from synapse.knowledge.quality import assess, is_artefact

CLEAN = (
    "Belediye meclisi, imar planı değişikliğine ilişkin teklifi görüşerek oy birliğiyle kabul "
    "etti. Kararın uygulanmasından fen işleri müdürlüğü sorumludur ve ilgili birimler gerekli "
    "çalışmaları başlatacaktır. Meclis üyeleri ayrıca bütçe raporunu inceledi, gelir ve gider "
    "kalemlerinin ayrıntılı olarak kamuoyuna duyurulmasına karar verdi. Toplantı saat on altıda "
    "sona erdi ve bir sonraki birleşimin tarihi başkanlık tarafından belirlenecektir."
)

# The same kind of text as a poor scanner OCR renders it: wrong letters, stray punctuation,
# case changes and "ıı" runs.
GARBLED = (
    "Bc,ledi.ve meclisi imar plaııı değişikliğine ilişkin tcklifi görüşcrck oy birliğiyle kabul "
    "cttı. Kararıı,ı uygulanıııasından fcn işlcri ınüdürlüğü sorum|udur ve ilgili birimlcr "
    "gcrckli çalışmaları başlatacaktır. MecLİS üyelcri ayrıca bütçc raporunu incelcdi, gelir "
    "ve gidcr kaleııılcrinin ayrıııtılı olarak kaıııuoyuııa duyurulmasına karar vcrdi. Toplaııtı "
    "saat on altıda sona crdi ve bir sonraki birleşiııııin tarihi başkanIık tarafıııdan "
    "belirlcnecektir."
)

NAMES = " ".join(
    f"{first} {last.upper()} AK PARTİ"
    for first, last in [
        ("Ayşe", "Yılmaz"),
        ("Mehmet", "Öztürk"),
        ("Hüseyin", "Çelebi"),
        ("Gülşen", "Karadağ"),
        ("İbrahim", "Ekinci"),
        ("Zeynep", "Şahin"),
        ("Oğuz", "Işıklı"),
        ("Fatma", "Güneş"),
    ]
)

TECHNICAL = (
    "Hastalara 10 mg/kg/gün dozunda verilir; ve/veya SARS-CoV-2 pozitif olanlarda HbA1c ve NaCl "
    "değerleri izlenir. KHK'nin II. ve III. bölümleri ile T.C. mevzuatı ve 5393 sayılı Kanunun "
    "ilgili maddeleri uyarınca işlem yapılır. Ayrıntılar için www.saglik.gov.tr adresine bakınız."
)

# A born-digital PDF with a broken font encoding: every glyph shifted.
BROKEN_ENCODING = (
    "KISALTMALAR $PHULND%LUOHúLN'HYOHWOHUL $QWLEL\\RWLN'X\\DUOÕOÕN7HVWL 'Õú.DOLWH'H÷HUOHQGLUPH "
    "(÷LWLPYH$UDúWÕUPD+DVWDQHVL QIHNVL\\RQ.RQWURO8]DNWDQ(÷LWLP3URJUDPÕ 6D÷OÕN+L]PHWLøOLúNLOL "
    "6WDQGDUGL]H(QIHNVL\\RQ2UDQÕ 6DQWUDO.DWHWHULOHøOLúNLOL.DQ'RODúÕPÕ(QIHNVL\\RQX "
) * 3


def test_clean_turkish_passes() -> None:
    result = assess(CLEAN)
    assert result.needs_ocr is False, result
    assert result.artefacts == 0


def test_bad_ocr_is_sent_to_ocr_again() -> None:
    result = assess(GARBLED)
    assert result.needs_ocr, result


def test_lists_of_names_are_not_mistaken_for_bad_ocr() -> None:
    assert assess(NAMES).needs_ocr is False


def test_technical_notation_is_not_an_artefact() -> None:
    result = assess(TECHNICAL)
    assert result.needs_ocr is False, result
    assert result.artefacts == 0


def test_a_broken_font_encoding_is_caught() -> None:
    assert assess(BROKEN_ENCODING).reason == "ocr_artefacts"


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("Bc,ledi.ve", True),
        ("sorum|ulukları", True),
        ("aıııacı", True),
        ("BELEDiyrsi", True),
        ("sERDivAN", True),
        ("mg/kg", False),
        ("SARS-CoV-2", False),
        ("KHK'nin", False),
        ("KHK’nin", False),
        ("III", False),
        ("İstanbul", False),
        ("İSTANBUL", False),
        ("HbA1c", False),
    ],
)
def test_artefacts(word: str, expected: bool) -> None:
    assert is_artefact(word) is expected


def test_turkish_lower_case() -> None:
    assert turkish.lower("IĞDIR İSTANBUL Işık") == "ığdır istanbul ışık"
    assert "i̇" not in turkish.lower("İ")  # no combining dot, unlike str.lower
