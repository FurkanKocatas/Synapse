"""Whose words a number is (chat/attribution.py), and what the answer does with a number put in
the wrong person's mouth."""

from synapse.chat.answering import Retrying
from synapse.chat.attribution import Misattributed, misattributed, names
from tests.test_chat import StandInChat, answerer, events_of, final, hit, says

# An expert report sums up two witnesses in one paragraph, as reports do.
REPORT = (
    '28.01.2026 tarihli celsede dinlenen davacı tanığı Aydın Kocabey, "Cumartesi 08:00 ile '
    "14:00 arası çalışırdık, hafta içi de akşam 18:30'a kadar kaldığımız olurdu.\" demiş; öğle "
    'arasının yarım saat olduğunu beyan etmiştir. Davalı tanığı Erol Tunçbilek ise "Cumartesi '
    "çalışması yarım gündü, hafta içi 17:00'de paydos.\" demiş; cumartesi 13:00'te çıkıldığını "
    "beyan etmiştir."
)
# The minute of the same hearing, read by OCR: headings in capitals.
MINUTE = (
    "DAVACI TANIĞI AYDIN KOCABEY: T.C. Kimlik No: ***********. Usulen yemini yapıldı, soruldu: "
    '"Cumartesi 08:00 ile 14:00 arası çalışırdık." dedi.\n'
    "DAVALI TANIĞI EROL TUNÇBİLEK: Üretim şefi olduğunu beyan etti. \"Cumartesi 13:00'te "
    'çıkılır." dedi.'
)


def test_people_are_found_by_their_names_without_roles_or_days() -> None:
    assert names(REPORT) == ["aydın kocabey", "erol tunçbilek"]
    assert names(MINUTE) == ["aydın kocabey", "erol tunçbilek"]
    assert names("Örnekşehir 3. İş Mahkemesi, Cumartesi Günü, T.C. Kimlik") == []


def test_a_number_given_to_the_wrong_witness_is_misattributed() -> None:
    wrong = "Aydın Kocabey, cumartesi 13:00'te çıkıldığını belirtmiştir. [1]"
    right = "Erol Tunçbilek, cumartesi 13:00'te çıkıldığını belirtmiştir. [1]"
    own = "Aydın Kocabey, cumartesi 08:00 ile 14:00 arası çalıştıklarını söylemiştir. [1]"
    for source in (REPORT, MINUTE):
        assert misattributed([wrong, right, own], [source], [1]) == (
            Misattributed(wrong, "aydın kocabey", ("13",)),
        )


def test_words_given_to_the_wrong_witness_are_misattributed() -> None:
    wrong = "Aydın Kocabey, cumartesi çalışmasının yarım gün olduğunu ifade etmiştir. [1]"
    own = "Aydın Kocabey, öğle arasının yarım saat olduğunu beyan etmiştir. [1]"
    numbers = "Aydın Kocabey, cumartesi 08:00 ile 14:00 arası çalıştıklarını söylemiştir. [1]"
    right = "Erol Tunçbilek, cumartesi çalışmasının yarım gün olduğunu söylemiştir. [1]"
    found = misattributed([wrong, own, numbers, right], [REPORT], [1])
    assert [(m.sentence, m.person) for m in found] == [(wrong, "aydın kocabey")]
    assert "yarım gün" in found[0].claims


def test_only_sentences_reporting_words_are_read_for_whose_they_are() -> None:
    plain = "Aydın Kocabey davasında cumartesi çıkış saati 13:00'tür. [1]"
    assert misattributed([plain], [REPORT], [1]) == ()


def test_a_number_before_anyone_speaks_decides_nothing() -> None:
    source = "Toplantı 13:00'te başladı. Davacı tanığı Aydın Kocabey bir şey söylemedi."
    sentence = "Aydın Kocabey toplantının 13:00'te başladığını söylemiştir. [1]"
    assert misattributed([sentence], [source], [1]) == ()


def test_a_person_the_cited_sources_do_not_name_is_not_checked() -> None:
    sentence = "Aydın Kocabey 13:00 dedi. [2]"
    assert misattributed([sentence], [REPORT, "Kurul 13 üyedir."], [2]) == ()


async def test_a_misattributed_number_is_retried_then_its_sentence_removed() -> None:
    hits = [hit(REPORT)]
    bad = says(
        ("Aydın Kocabey, cumartesi 08:00 ile 14:00 arası çalıştıklarını söylemiştir.", [1]),
        ("Aydın Kocabey, cumartesi 13:00'te çıkıldığını belirtmiştir.", [1]),
    )
    chat = StandInChat(bad, bad)
    events = await events_of(answerer(hits, chat), "Aydın Kocabey cumartesi hakkında ne dedi?")
    assert [e for e in events if isinstance(e, Retrying)] == [Retrying(("13",))]
    assert "13 (aydın kocabey)" in chat.calls[1][-1].content
    answer = final(events)
    assert answer.status == "answered"
    assert answer.text == (
        "Aydın Kocabey, cumartesi 08:00 ile 14:00 arası çalıştıklarını söylemiştir. [1]"
    )
    assert answer.stripped == ("Aydın Kocabey, cumartesi 13:00'te çıkıldığını belirtmiştir. [1]",)


async def test_a_corrected_answer_is_kept_whole() -> None:
    hits = [hit(REPORT)]
    bad = says(("Aydın Kocabey, cumartesi 13:00'te çıkıldığını belirtmiştir.", [1]))
    good = says(("Erol Tunçbilek, cumartesi 13:00'te çıkıldığını belirtmiştir.", [1]))
    answer = final(await events_of(answerer(hits, StandInChat(bad, good)), "Kim ne dedi?"))
    assert (answer.status, answer.retried) == ("answered", True)
    assert answer.text == "Erol Tunçbilek, cumartesi 13:00'te çıkıldığını belirtmiştir. [1]"
