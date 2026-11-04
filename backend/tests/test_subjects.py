from synapse.chat.subjects import other_organisation

ORDU = (
    "2024-faaliyet-raporu, sayfa 30\n"
    "Belgenin başı: ORDU BÜYÜKŞEHİR BELEDİYESİ 2024 FAALİYET RAPORU\n"
    "Personel Durumu Memur 412 İşçi 1.779 Toplam 2.191"
)
TRABZON = "Trabzon Büyükşehir Belediyesi'nin 2024 faaliyet raporuna göre toplam personel sayısı?"


def test_an_answer_from_another_municipality_is_caught() -> None:
    # The golden set's u-01: Ordu's staff count was given as Trabzon's.
    assert other_organisation(TRABZON, [ORDU], [1])
    assert not other_organisation(
        "Ordu Büyükşehir Belediyesi'nin 2024 raporuna göre personel sayısı?", [ORDU], [1]
    )


def test_only_the_cited_sources_count() -> None:
    trabzon = "Belgenin başı: TRABZON BÜYÜKŞEHİR BELEDİYESİ 2024 FAALİYET RAPORU Toplam 3.050"
    assert not other_organisation(TRABZON, [ORDU, trabzon], [2])
    assert other_organisation(TRABZON, [ORDU, trabzon], [1])
    assert not other_organisation(TRABZON, [ORDU], [])


def test_a_source_naming_no_organisation_decides_nothing() -> None:
    # A strategic plan's pages name the municipality only by its web address.
    plan = "Belgenin başı: www.usak.bel.tr Sayfa 28 STRATEJİK PLAN Hedef 1.1 gerçekleşme %99"
    question = "Uşak Belediyesi 2025-2029 stratejik planında hedef?"
    assert not other_organisation(question, [plan], [1])


def test_the_one_asked_about_standing_in_a_cited_source_is_enough() -> None:
    # Şile's decision names İstanbul's municipality too.
    decision = (
        "T.C. ŞİLE BELEDİYE BAŞKANLIĞI Karar No: 2026/54 İstanbul Büyükşehir Belediyesi Deprem "
        "ve Zemin İnceleme Şube Müdürlüğü görüşü alınmıştır."
    )
    question = "Şile Belediye Meclisinin 2026/54 sayılı kararı?"
    assert not other_organisation(question, [decision], [1])
    # An OCR'd page without Turkish letters is still Şile's.
    ocr = "SILE BELEDIYE BASKANLIGI Karar No: 2026/54 ISTANBUL BUYUKSEHIR BELEDIYESI"
    assert not other_organisation(question, [ocr], [1])


def test_words_that_do_not_name_an_organisation_are_left_out() -> None:
    # Lower case, "Belediyemiz" (our own) and "T.C." name nobody.
    source = "T.C. Belediyemiz encümeni, göre belediye ve EFELER BELEDİYESİ kararı"
    assert not other_organisation("Belediyemiz encümeni hangi gün toplanır?", [source], [1])
    assert not other_organisation("Kurul kaç üyedir?", [source], [1])
    assert other_organisation("Erzurum Büyükşehir Belediyesi'nin planında kaç amaç?", [source], [1])


def test_other_kinds_of_organisation_are_compared_within_their_kind() -> None:
    bar = "Belgenin başı: İSTANBUL BAROSU Avukatlıkta yapay zekâ rehberi"
    assert other_organisation("Ankara Barosu'nun rehberine göre?", [bar], [1])
    # A municipality asked about, a bar named: different kinds decide nothing.
    assert not other_organisation(TRABZON, [bar], [1])
