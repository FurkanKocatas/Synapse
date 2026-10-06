"""Grounded answers without a database: verification, context, streaming, refusal and the queue.

Search and the chat model are stand-ins; tests/db/test_chat.py runs the same flow on PostgreSQL.
"""

import asyncio
import json
from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import aclosing
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from synapse.chat.answering import (
    PER_DOCUMENT,
    SOURCE_TOKENS,
    SOURCES,
    Answer,
    Answerer,
    AnswerStream,
    Delta,
    Event,
    Gate,
    Generating,
    Queued,
    Retrying,
    Rewritten,
    Sources,
    Turn,
    assemble,
    parse,
    schema,
    source_text,
    written,
)
from synapse.chat.numerals import numeric
from synapse.chat.talk import CLASSIC_TURNS, moment, small_talk
from synapse.chat.verification import check, cited, claims, sentences, strip_unsupported
from synapse.knowledge.public import EVERYTHING, Folder, Found, Hit, Listed, Overview, Scope
from synapse.models.public import ChatDelta, ChatMessage, ChatReply, ModelUnavailableError

USER = uuid4()
REFUSE_BELOW = -1.0
# What the stand-in search says the user's documents are.
LIBRARY = Overview(
    [Folder("Mali İşler", 1), Folder("Mali İşler / Bütçe 2026", 1)],
    [
        Listed(
            "2026 Bütçe Kararnamesi",
            "Mali İşler / Bütçe 2026",
            "application/pdf",
            "ready",
            datetime(2026, 10, 2, 9, 30, tzinfo=UTC),
            48,
            "T.C. Belediye Meclisi 2026 mali yılı bütçesi",
        ),
        Listed(
            "Kadro Cetveli",
            "Mali İşler",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "ocr",
            datetime(2026, 9, 28, 14, 0, tzinfo=UTC),
            3,
            "Norm kadro cetveli",
        ),
    ],
    total=2,
    ready=1,
    failed=0,
)


def hit(text: str, *, score: float | None = 2.0, document: UUID | None = None, n: int = 0) -> Hit:
    return Hit(
        document_id=document or uuid4(),
        title=f"Belge {n}",
        version_id=uuid4(),
        version=1,
        ordinal=n,
        kind="text",
        heading_path=("Bölüm",),
        text=text,
        page_start=n + 1,
        page_end=n + 1,
        context="",
        lexical_rank=n + 1,
        dense_rank=None,
        reranked=score is not None,
        rerank_score=score,
    )


class StandInSearch:
    def __init__(self, hits: list[Hit], *, reranked: bool = True) -> None:
        self.hits = hits
        self.reranked = reranked
        self.queries: list[str] = []
        self.scopes: list[Scope] = []

    async def candidates(
        self, user_id: UUID, query: str, *, limit: int = 15, scope: Scope = EVERYTHING
    ) -> Found:
        self.queries.append(query)
        self.scopes.append(scope)
        # The first stage's order: the reranker's, reversed.
        return Found(self.hits[:limit][::-1], reranked=False, warnings=[], milliseconds={})

    async def rerank(self, query: str, found: Found, *, limit: int) -> Found:
        return Found(self.hits[:limit], reranked=self.reranked, warnings=[], milliseconds={})

    async def library(self, user_id: UUID, scope: Scope = EVERYTHING) -> Overview:
        self.scopes.append(scope)
        return LIBRARY


class StandInChat:
    """Replies in turn from ``replies``: a dict becomes the JSON reply, split into deltas; a
    string is a plain-text reply. ``route`` is what a message the search found nothing for is
    judged to be."""

    def __init__(
        self, *replies: dict[str, Any] | str | Exception, rewrite: str = "", route: str = ""
    ) -> None:
        self.replies = list(replies)
        self.rewrite = rewrite
        self.route = route
        self.calls: list[list[ChatMessage]] = []
        self.schemas: list[Mapping[str, Any] | None] = []
        self.closed = 0
        self.release: asyncio.Event | None = None

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        schema: Mapping[str, Any] | None = None,
        max_tokens: int = 1024,
    ) -> ChatReply:
        self.calls.append(list(messages))
        if schema is not None and "kind" in schema["properties"]:
            return ChatReply(json.dumps({"kind": self.route}))
        if isinstance(self.rewrite, Exception):
            raise self.rewrite
        return ChatReply(json.dumps({"question": self.rewrite}))

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        schema: Mapping[str, Any] | None = None,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[ChatDelta | ChatReply]:
        self.calls.append(list(messages))
        self.schemas.append(schema)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        content = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        try:
            for start in range(0, len(content), 7):
                if self.release is not None:
                    await self.release.wait()
                yield ChatDelta(content[start : start + 7])
            yield ChatReply(content, prompt_tokens=100)
        finally:
            self.closed += 1


def answerer(hits: list[Hit], chat: StandInChat | None, **options: Any) -> Answerer:
    search = StandInSearch(hits, **options)
    return Answerer(search, chat, refuse_below=REFUSE_BELOW)  # type: ignore[arg-type]


async def events_of(source: Answerer, question: str, history: Sequence[Turn] = ()) -> list[Event]:
    return [event async for event in source.answer(USER, question, history)]


def final(events: list[Event]) -> Answer:
    answer = events[-1]
    assert isinstance(answer, Answer)
    return answer


# Verification


def test_numbers_are_compared_as_numbers() -> None:
    assert numeric("302.250.000 tl") == "302250000 tl"
    assert numeric("üç yıl, oniki gün") == "3 yıl, 12 gün"
    assert numeric("dokuz yüz yirmi bin lira") == "920000 lira"
    assert numeric("5 bin kişi") == "5000 kişi"
    assert numeric("üçüncü madde 22.12.2023 99,5") == "üçüncü madde 22.12.2023 99,5"


def test_claims_are_the_tokens_with_digits_without_citations() -> None:
    text = "Karar 22.12.2023 tarih ve 2023/1497 sayılıdır [1]. Bedel 302.250.000 TL'dir [2, 3]."
    assert claims(text) == ["22.12.2023", "2023/1497", "302250000"]
    assert claims("Üç yıl sürer.") == ["3"]
    assert cited(text) == [1, 2, 3]


def test_a_claim_must_stand_whole_in_a_cited_source() -> None:
    sources = [
        "Encümenin 22.12.2023 tarih 2023/1497 sayılı kararı",
        "Toplam bedel 302.250.000,00 TL olarak belirlenmiştir.",
        "Belge numarası E-91810702",
    ]
    ok = check("2023/1497 sayılı karar [1], bedel 302250000 TL [2].", sources, [1, 2])
    assert ok.ok
    assert ok.uncited == ()
    # In a source shown but not cited: grounded, the citation is what is missing.
    uncited = check("Bedel 302250000 TL [1].", sources, [1])
    assert (uncited.uncited, uncited.lacking, uncited.ok) == (("302250000",), (2,), True)
    # Changed identifiers and digit groups of another number are not supported.
    changed = check("Numara E91810702 [3], karar 1497/2023 [1], 14970 [1].", sources, [1, 3])
    assert changed.unsupported == ("e91810702", "1497/2023", "14970")
    assert check("2023 yılında [1].", sources, [1]).ok


def test_sentences_end_at_full_stops_but_not_at_ordinals_or_abbreviations() -> None:
    text = (
        "Kanunun 18. maddesi uygulanır [1]. Md. 5 de geçerlidir [2]. "
        "Bedel 5 TL'dir! Süre üç yıldır [1]"
    )
    assert sentences(text) == [
        "Kanunun 18. maddesi uygulanır [1].",
        "Md. 5 de geçerlidir [2].",
        "Bedel 5 TL'dir!",
        "Süre üç yıldır [1]",
    ]


def test_sentences_with_unsupported_claims_are_removed() -> None:
    kept, removed = strip_unsupported("Kurul 7 üyedir [1]. Toplantı 12 Mart'tadır [2].", ["12"])
    assert kept == "Kurul 7 üyedir [1]."
    assert removed == ("Toplantı 12 Mart'tadır [2].",)


# Context and parsing


def test_the_context_keeps_order_limits_documents_and_drops_duplicates() -> None:
    same = uuid4()
    hits = [hit(f"metin {i} " + "kelime " * i, document=same, n=i) for i in range(4)]
    duplicate = hit(hits[0].text + " ek", n=9)
    others = [hit(f"başka {i} belge", n=10 + i) for i in range(6)]
    picked = assemble([*hits, duplicate, *others])
    assert len(picked) == SOURCES
    assert picked[:PER_DOCUMENT] == hits[:PER_DOCUMENT]
    assert duplicate not in picked
    assert picked[PER_DOCUMENT:] == others[: SOURCES - PER_DOCUMENT]


def test_the_context_stays_within_its_token_budget() -> None:
    long = hit("uzun " * (SOURCE_TOKENS * 2), n=0)
    short = hit("kısa metin", n=1)
    assert assemble([long, short]) == [short]
    assert source_text(short) == "Belge 1, sayfa 2\nBölüm\nkısa metin"


def says(*sentences: tuple[str, list[int]], sufficient: bool = True) -> dict[str, Any]:
    """A reply in the schema's shape."""
    return {
        "answer": [{"text": text, "sources": numbers} for text, numbers in sentences],
        "sufficient": sufficient,
    }


def test_the_schema_makes_every_sentence_cite_a_source_shown() -> None:
    answer = schema(4)["properties"]["answer"]  # type: ignore[index]
    sentence = answer["items"]
    assert answer["minItems"] == 1
    assert sentence["required"] == ["text", "sources"]
    assert sentence["properties"]["sources"]["minItems"] == 1
    assert sentence["properties"]["sources"]["items"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 4,
    }


def test_sentences_are_written_with_their_citations() -> None:
    assert written([("Kurul 7 üyedir. ", [1]), (" ", [2]), ("Ayda bir toplanır.", [1, 3])]) == (
        "Kurul 7 üyedir. [1] Ayda bir toplanır. [1, 3]"
    )
    assert written([("Tanımsız.", [])]) == "Tanımsız."


def test_replies_are_parsed_leniently() -> None:
    reply = json.dumps(says(("Kurul 7 üyedir.", [1]), ("Başkan seçer.", [2, 1])))
    assert parse(reply) == ("Kurul 7 üyedir. [1] Başkan seçer. [2, 1]", True)
    odd = '{"answer": [{"text": "A.", "sources": [1, "x"]}, {"text": 5}, 7], "sufficient": true}'
    assert parse(odd) == ("A. [1]", True)
    assert parse('{"answer": " 7 üye [1] ", "sufficient": true}') == ("7 üye [1]", True)
    assert parse('{"answer": "Belgelerde bulunamadı.", "sufficient": false}')[1] is False
    assert parse("düz metin") == ("düz metin", True)
    assert parse("[1]") == ("[1]", True)
    assert parse('{"sufficient": true}') == ("", True)


@pytest.mark.parametrize("size", [1, 2, 3, 5, 100])
def test_the_answer_is_shown_as_it_streams(size: int) -> None:
    reply = says(('Kurul "yedi" üyedir\\.', [1]), ("€ 😀 [sic]", [2, 3]), ("", [1]))
    content = json.dumps(reply, ensure_ascii=True)
    stream = AnswerStream()
    shown = ""
    for i in range(0, len(content), size):
        shown += stream.feed(content[i : i + size])
        # Never more than the start of the whole answer.
        assert parse(content)[0].startswith(shown)
    assert shown == parse(content)[0] == 'Kurul "yedi" üyedir\\. [1] € 😀 [sic] [2, 3]'


def test_a_sentence_shows_before_its_citations_close() -> None:
    stream = AnswerStream()
    assert stream.feed('{"answer": [{"text": "Kurul 7 ü') == "Kurul 7 ü"
    assert stream.feed('yedir.", "sources": [1, ') == "yedir."
    assert stream.feed("2]}") == " [1, 2]"


# The flow


async def test_an_answer_streams_after_its_sources_and_is_verified() -> None:
    hits = [hit("Kurul yedi üyeden oluşur.", n=0), hit("Toplantı ayda bir yapılır.", n=1)]
    chat = StandInChat(says(("Kurul 7 üyeden oluşur.", [1])))
    events = await events_of(answerer(hits, chat), "Kurul kaç üyeden oluşur?")
    # The first stage's order at once, then the reranker's.
    assert events[0] == Sources(hits[::-1], [], ranked=False)
    assert events[1] == Sources(hits, [], ranked=True)
    assert isinstance(events[2], Generating)
    assert "".join(e.text for e in events if isinstance(e, Delta)) == "Kurul 7 üyeden oluşur. [1]"
    answer = final(events)
    assert (answer.status, answer.text, answer.citations) == (
        "answered",
        "Kurul 7 üyeden oluşur. [1]",
        [1],
    )
    assert chat.schemas == [schema(2)]
    assert answer.checked is not None and answer.checked.claims == ("7",)
    assert answer.best_score == 2.0
    (messages,) = chat.calls
    assert messages[1].content.startswith("Kaynaklar:\n\n[1] Belge 0, sayfa 1\nBölüm\nKurul")
    assert messages[1].content.endswith("Soru: Kurul kaç üyeden oluşur?")


async def test_a_low_score_about_the_organisation_is_refused_without_an_answer() -> None:
    chat = StandInChat(route="documents")
    hits = [hit("İlgisiz bir metin.", score=REFUSE_BELOW - 0.1)]
    events = await events_of(answerer(hits, chat), "Konser ne zaman?")
    assert isinstance(events[0], Sources)  # shown as possibly related
    assert final(events).status == "not_found"
    # The model only said what the question is; it wrote no answer.
    assert chat.schemas == []
    assert final(await events_of(answerer([], chat), "Konser ne zaman?")).status == "not_found"


@pytest.mark.parametrize(
    "message",
    [
        "Selam",
        "merhaba!",
        "Günaydın hocam",
        "selam, nasılsın?",
        "Teşekkürler 🙏",
        "Sağol",
        "thanks",
    ],
)
def test_small_talk_is_only_greetings_thanks_and_farewells(message: str) -> None:
    assert small_talk(message)


@pytest.mark.parametrize(
    "message",
    [
        "Merhaba, 2026 bütçesi ne kadar?",
        "Teşekkürler, peki meclis kaç üyeli?",
        "Selam verme yönetmeliği",
        "Tamam mı bu karar?",
        "",
    ],
)
def test_a_question_with_a_greeting_is_not_small_talk(message: str) -> None:
    assert not small_talk(message)


async def test_a_greeting_is_answered_as_conversation_without_a_search() -> None:
    chat = StandInChat("Merhaba! Belgelerinizle ilgili ne sormak istersiniz?")
    source = answerer([hit("Kurul 7 üyedir.")], chat)
    history = [Turn("Kurul kaç üyeli?", "Kurul 7 üyedir. [1]")]
    events = await events_of(source, "Selam", history)
    assert not any(isinstance(event, Sources) for event in events)
    assert source._search.queries == []  # type: ignore[attr-defined]
    answer = final(events)
    assert (answer.status, answer.kind, answer.citations) == ("answered", "conversation", [])
    assert answer.text == "Merhaba! Belgelerinizle ilgili ne sormak istersiniz?"
    assert "".join(e.text for e in events if isinstance(e, Delta)) == answer.text
    (messages,) = chat.calls
    # The conversation so far, without its citation markers, then the greeting.
    assert [m.role for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[2].content == "Kurul 7 üyedir."
    assert chat.schemas == [None]


async def test_a_question_of_general_knowledge_is_answered_and_marked() -> None:
    chat = StandInChat("Fotosentez, bitkilerin ışıkla besin üretmesidir.", route="general")
    hits = [hit("İlgisiz bir metin.", score=REFUSE_BELOW - 0.1)]
    events = await events_of(answerer(hits, chat), "Fotosentez nedir?")
    answer = final(events)
    assert (answer.status, answer.kind, answer.citations) == ("answered", "general", [])
    assert any(isinstance(event, Generating) for event in events)


async def test_general_answers_can_be_turned_off() -> None:
    chat = StandInChat("Fotosentez...", route="general")
    search = StandInSearch([hit("İlgisiz bir metin.", score=REFUSE_BELOW - 0.1)])
    source = Answerer(search, chat, refuse_below=REFUSE_BELOW, general=False)  # type: ignore[arg-type]
    answer = final(await events_of(source, "Fotosentez nedir?"))
    assert (answer.status, answer.kind) == ("not_found", "documents")
    assert chat.schemas == []


async def test_a_message_the_model_calls_conversation_is_answered_so() -> None:
    chat = StandInChat(
        "Ben Synapse; belgelerinizden kaynaklı cevaplar veririm.", route="conversation"
    )
    hits = [hit("İlgisiz bir metin.", score=REFUSE_BELOW - 0.1)]
    answer = final(await events_of(answerer(hits, chat), "Sen kimsin?"))
    assert (answer.status, answer.kind) == ("answered", "conversation")


async def test_without_reranker_scores_the_model_decides() -> None:
    chat = StandInChat({"answer": "Belgelerde bulunamadı.", "sufficient": False})
    events = await events_of(answerer([hit("metin", score=None)], chat, reranked=False), "Soru?")
    assert final(events).status == "insufficient"
    # The answer, then what the message is (a question to the documents: refused).
    assert len(chat.calls) == 2


async def test_a_refused_message_that_asks_the_documents_nothing_is_answered() -> None:
    chat = StandInChat(
        {"answer": "Belgelerde bulunamadı.", "sufficient": False},
        "Bugün 2 Ekim 2026, Cuma.",
        route="general",
    )
    events = await events_of(answerer([hit("Kurul 7 üyedir.")], chat), "Bugün günlerden ne?")
    answer = final(events)
    assert (answer.status, answer.kind, answer.text) == (
        "answered",
        "general",
        "Bugün 2 Ekim 2026, Cuma.",
    )
    # The page starts the answer over when the reply comes.
    assert sum(isinstance(event, Generating) for event in events) == 2


def test_the_time_is_written_as_the_user_reads_it() -> None:
    istanbul = timezone(timedelta(hours=3))
    assert moment(datetime(2026, 10, 2, 13, 5, tzinfo=istanbul)) == (
        "Şu an 2 Ekim 2026 Cuma, saat 13:05."
    )
    assert moment(None).startswith("Şu an ")


async def test_a_reply_knows_the_users_day() -> None:
    chat = StandInChat("Merhaba!")
    now = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)
    source = answerer([], chat)
    events = [event async for event in source.answer(USER, "Günaydın", (), now)]
    assert final(events).kind == "conversation"
    assert "2 Ekim 2026 Cuma, saat 10:00" in chat.calls[0][0].content


async def test_a_classic_conversation_searches_nothing_and_keeps_its_history() -> None:
    chat = StandInChat("İşte bir taslak: ...")
    search = StandInSearch([hit("Kurul 7 üyedir.")])
    source = Answerer(search, chat, refuse_below=REFUSE_BELOW)  # type: ignore[arg-type]
    history = [Turn(f"Soru {n}", f"Cevap {n} [1]") for n in range(CLASSIC_TURNS + 2)]
    events = [event async for event in source.classic("Bir e-posta yaz", history)]
    assert search.queries == []
    assert not any(isinstance(event, Sources) for event in events)
    answer = final(events)
    assert (answer.status, answer.kind, answer.citations) == ("answered", "general", [])
    (messages,) = chat.calls
    assert messages[0].content.startswith("Sen yardımsever bir asistansın.")
    # The last turns only, without citation markers, then the message.
    assert len(messages) == 1 + 2 * CLASSIC_TURNS + 1
    assert messages[1].content == "Soru 2" and messages[2].content == "Cevap 2"
    assert chat.schemas == [None]


async def test_a_classic_conversation_without_a_chat_model_fails() -> None:
    source = Answerer(StandInSearch([]), None, refuse_below=REFUSE_BELOW)  # type: ignore[arg-type]
    answer = final([event async for event in source.classic("Merhaba")])
    assert (answer.status, answer.error) == ("failed", "chat_unconfigured")


@pytest.mark.parametrize(
    "reply",
    [
        {"answer": "Belgelerde bulunamadı.", "sufficient": True},
        {"answer": "Kısmen 7 [1].", "sufficient": False},
        {"answer": "", "sufficient": True},
    ],
)
async def test_the_model_saying_the_sources_do_not_suffice_is_no_answer(
    reply: dict[str, Any],
) -> None:
    events = await events_of(answerer([hit("Kurul 7 üyedir.")], StandInChat(reply)), "Soru?")
    assert (final(events).status, final(events).text) == ("insufficient", "")


async def test_an_unsupported_number_is_retried_once() -> None:
    chat = StandInChat(
        {"answer": "Kurul 9 üyedir [1].", "sufficient": True},
        {"answer": "Kurul 7 üyedir [1].", "sufficient": True},
    )
    events = await events_of(answerer([hit("Kurul 7 üyedir.")], chat), "Kaç üye?")
    retry = [e for e in events if isinstance(e, Retrying)]
    assert retry == [Retrying(("9",))]
    answer = final(events)
    assert (answer.status, answer.text, answer.retried) == ("answered", "Kurul 7 üyedir [1].", True)
    second = chat.calls[1]
    assert second[-2] == ChatMessage(
        "assistant", '{"answer": "Kurul 9 üyedir [1].", "sufficient": true}'
    )
    assert "9" in second[-1].content


async def test_still_unsupported_sentences_are_removed() -> None:
    bad = {"answer": "Kurul 7 üyedir [1]. Başkan 3 yıl görev yapar [1].", "sufficient": True}
    events = await events_of(answerer([hit("Kurul 7 üyedir.")], StandInChat(bad, bad)), "Soru?")
    answer = final(events)
    assert (answer.status, answer.text) == ("answered", "Kurul 7 üyedir [1].")
    assert answer.stripped == ("Başkan 3 yıl görev yapar [1].",)

    only_bad = {"answer": "Başkan 3 yıl görev yapar [1].", "sufficient": True}
    chat = StandInChat(only_bad, only_bad)
    answer = final(await events_of(answerer([hit("Kurul 7 üyedir.")], chat), "Soru?"))
    assert (answer.status, answer.text, answer.stripped) == (
        "insufficient",
        "",
        ("Başkan 3 yıl görev yapar [1].",),
    )


async def test_a_number_from_an_uncited_source_adds_its_citation() -> None:
    hits = [hit("Kurul toplanır.", n=0), hit("Kurul 7 üyedir.", n=1)]
    chat = StandInChat({"answer": "Kurul 7 üyedir [1].", "sufficient": True})
    answer = final(await events_of(answerer(hits, chat), "Soru?"))
    assert (answer.status, answer.citations) == ("answered", [1, 2])


async def test_citations_out_of_range_are_dropped() -> None:
    chat = StandInChat({"answer": "Kurul toplanır [1, 8].", "sufficient": True})
    answer = final(await events_of(answerer([hit("Kurul toplanır.")], chat), "Soru?"))
    assert answer.citations == [1]


async def test_a_model_failure_is_a_failed_answer_after_the_sources() -> None:
    chat = StandInChat(ModelUnavailableError("chat", "down"))
    events = await events_of(answerer([hit("metin")], chat), "Soru?")
    assert isinstance(events[0], Sources)
    assert (final(events).status, final(events).error) == ("failed", "chat_unavailable")
    events = await events_of(answerer([hit("metin")], None), "Soru?")
    assert (final(events).status, final(events).error) == ("failed", "chat_unconfigured")


async def test_a_follow_up_is_rewritten_and_the_rewrite_searched() -> None:
    chat = StandInChat({"answer": "7 [1].", "sufficient": True}, rewrite="Kurul kaç üyedir?")
    source = answerer([hit("Kurul 7 üyedir.")], chat)
    history = [Turn("Kurul nedir? [1]", "Bir organdır [1].")] * 5
    events = await events_of(source, "Kaç üyesi var?", history)
    assert events[0] == Rewritten("Kurul kaç üyedir?")
    assert source._search.queries == ["Kurul kaç üyedir?"]  # type: ignore[attr-defined]
    rewrite = chat.calls[0][1].content
    assert rewrite.count("Soru: ") == 3  # the last three turns
    assert "[1]" not in rewrite.split("Son soru:")[0].split("Soru: Kurul nedir? [1]")[1]
    assert rewrite.endswith("Son soru: Kaç üyesi var?")
    assert final(events).question == "Kurul kaç üyedir?"


async def test_a_failed_or_empty_rewrite_keeps_the_question() -> None:
    for chat in (
        StandInChat({"answer": "7 [1].", "sufficient": True}, rewrite=""),
        StandInChat({"answer": "7 [1].", "sufficient": True}, rewrite="Kaç üyesi var?"),
    ):
        source = answerer([hit("Kurul 7 üyedir.")], chat)
        events = await events_of(source, "Kaç üyesi var?", [Turn("Kurul?", "Organ.")])
        assert not any(isinstance(e, Rewritten) for e in events)
        assert source._search.queries == ["Kaç üyesi var?"]  # type: ignore[attr-defined]
    failing = StandInChat({"answer": "7 [1].", "sufficient": True})
    failing.rewrite = ModelUnavailableError("chat", "down")  # type: ignore[assignment]
    events = await events_of(answerer([hit("Kurul 7 üyedir.")], failing), "Kaç?", [Turn("a", "b")])
    assert final(events).status == "answered"


# The queue


def test_the_gate_serves_in_order_and_hands_slots_over() -> None:
    gate = Gate(slots=1)
    first, second, third = gate.enter(), gate.enter(), gate.enter()
    assert first.is_set() and not second.is_set()
    assert (gate.position(second), gate.position(third)) == (1, 2)
    gate.leave(third)  # gave up waiting
    gate.leave(first)
    assert second.is_set()
    gate.leave(second)
    assert gate.enter().is_set()


async def test_a_turn_waits_for_a_slot_and_says_where_it_stands() -> None:
    gate = Gate(slots=1)
    busy = gate.enter()
    chat = StandInChat({"answer": "Kurul toplanır [1].", "sufficient": True})
    source = Answerer(
        StandInSearch([hit("Kurul toplanır.")]),  # type: ignore[arg-type]
        chat,
        refuse_below=REFUSE_BELOW,
        gate=gate,
    )
    events: list[Event] = []
    queued = asyncio.Event()

    async def run() -> None:
        async for event in source.answer(USER, "Soru?"):
            events.append(event)
            if isinstance(event, Queued):
                queued.set()

    task = asyncio.create_task(run())
    await asyncio.wait_for(queued.wait(), 5)
    assert events[-1] == Queued(1)
    gate.leave(busy)
    await task
    assert isinstance(events[-1], Answer)
    assert gate.enter().is_set()  # the turn gave its slot back


async def test_closing_a_turn_stops_the_model_and_frees_its_slot() -> None:
    gate = Gate(slots=1)
    chat = StandInChat(says(("Kurul toplanır.", [1])))
    source = Answerer(
        StandInSearch([hit("Kurul toplanır.")]),  # type: ignore[arg-type]
        chat,
        refuse_below=REFUSE_BELOW,
        gate=gate,
    )
    async with aclosing(source.answer(USER, "Soru?")) as events:
        async for event in events:
            if isinstance(event, Delta):
                break
    assert chat.closed == 1  # the model's stream was closed, not left to the collector
    assert gate.enter().is_set()
