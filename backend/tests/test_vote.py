"""The vote over a page's readings (knowledge/vote.py), on readings small enough to follow."""

from synapse.knowledge.vote import Token, agreement, in_order_of, present, vote, words


def test_the_reading_most_voices_give_wins() -> None:
    pivot = "Meclis 2026/35 sayılı kararı kabul etti"
    assert (
        vote(
            [
                pivot,
                "Meclis 2026/36 sayılı kararı kabul etti",
                "Meclis 2026/35 sayili kararı kabul etti",
            ]
        )
        == pivot
    )
    # all three differ: the pivot's reading
    assert vote(["karar 35", "karar 36", "karar 37"]) == "karar 35"


def test_a_word_the_pivot_missed_is_added_when_most_others_read_it() -> None:
    pivot = "Meclis kararı kabul etti"
    both = "Meclis bu kararı kabul etti"
    assert vote([pivot, both, both]) == both
    assert vote([pivot, both, pivot]) == pivot


def test_a_word_most_voices_did_not_read_is_left_out() -> None:
    looping = "Meclis kararı kabul etti kabul etti kabul etti"
    others = "Meclis kararı kabul etti"
    assert vote([looping, others, others]) == "Meclis kararı kabul etti"


def test_nothing_new_is_written() -> None:
    readings = ["İzmir 2026", "Izmir 2O26", "lzmir 2026"]
    assert set(vote(readings).split()) <= {w for r in readings for w in r.split()}


def test_the_pivots_lines_and_punctuation_stay() -> None:
    pivot = "Tutar 12.500 TL,\nkabul edlldi."
    others = ["Tutar 12.500 TL kabul edildi", "Tutar 12.500 TL, kabul edildi!"]
    assert vote([pivot, *others]) == "Tutar 12.500 TL,\nkabul edildi."


def test_an_added_word_goes_on_the_line_of_the_pivot_word_before_it() -> None:
    both = "Meclis bu kararı kabul etti"
    assert vote(["Meclis\nkararı kabul etti", both, both]) == "Meclis bu\nkararı kabul etti"


def test_the_pivots_tokens_without_a_letter_or_digit_stay() -> None:
    others = "Madde 5 yürürlük"
    assert vote(["• Madde 5 - yürürlük", others, others]) == "• Madde 5 - yürürlük"


def test_words_are_joined_across_line_end_hyphens() -> None:
    assert vote(["sü-\nresi doldu", "süresi doldu", "süresi doldu"]) == "süresi doldu"


def test_the_trusted_voices_circumflexes_go_on_the_chosen_word() -> None:
    readings = ["malî hizmetler", "mali hizmetler", "mali hizmetler"]
    assert vote(readings) == "mali hizmetler"
    assert vote(readings, hats=0) == "malî hizmetler"
    # circumflexes go on letters only, never on another word
    assert vote(["iddia", "idari", "idari"], hats=0) == "idari"


def test_letters_turkish_has_not_become_the_turkish_letter_they_look_like() -> None:
    readings = ["karșı Ístanbul siyasì", "karşı İstanbul siyasî", "karsi Istanbul siyasi"]
    assert vote(readings) == "karşı İstanbul siyasî"


def test_a_voice_that_failed_on_a_page_does_not_vote() -> None:
    assert present([6, 6, 0, 1, 6]) == [0, 1, 4]
    pivot = "Meclis kararı kabul edildi ve yayımlandı"
    # left out, it does not count
    assert vote([pivot, "", pivot]) == pivot


def test_lines_read_in_another_order_are_put_in_the_pivots() -> None:
    def line(text: str, number: int) -> list[Token]:
        return [Token(w, w, number) for w in text.split()]

    pivot = ["Birinci", "sütunun", "metni", "burada", "İkinci", "sütun", "şöyle", "devam", "eder"]
    chunks = [line("İkinci sütun şöyle devam eder", 0), line("Birinci sütunun metni burada", 1)]
    reordered = [t.key for t in in_order_of(pivot, chunks)]
    assert reordered == pivot
    as_read = [t.key for chunk in chunks for t in chunk]
    assert agreement(pivot, [reordered]) > agreement(pivot, [as_read])


def test_two_columns_read_in_another_order_still_vote_word_by_word() -> None:
    pivot = "Birinci sütunun metni burada\nİkinci sütun şöyle devam eder"
    swapped = "İkinci sütun şöyle devam eder\nBirinci sütunun metni burada"
    # as read, the swapped voice pairs other words with "metnı"; put in order, it outvotes it
    assert vote([pivot.replace("metni", "metnı"), swapped, pivot]) == pivot


def test_words_are_compared_without_their_edge_punctuation() -> None:
    assert [t.key for t in words("«Karar», (2026/35) ve - •")] == ["Karar", "2026/35", "ve"]
