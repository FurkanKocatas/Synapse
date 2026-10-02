"""Questions about the collection itself ("belgelerde neler var"), answered from what its
documents are (knowledge/library.py), and conversation that knows them (chat/talk.py)."""

import json
from pathlib import Path

import pytest

from synapse.chat.talk import about_library, describe, summary
from synapse.knowledge.public import Overview
from tests.test_chat import (
    LIBRARY,
    StandInChat,
    answerer,
    events_of,
    final,
    hit,
)

GOLDEN = Path(__file__).resolve().parents[2] / "eval" / "golden"


@pytest.mark.parametrize(
    "message",
    [
        "Belgelerin içerisinde neler var?",
        "Belgelerde neler var",
        "Dosyalarımızda ne var?",
        "Hangi belgeler var?",
        "Hangi klasörlere erişebiliyorum?",
        "Sistemde kaç belge var?",
        "Kaç tane dosya yüklü?",
        "Belgeleri listele",
        "Ne tür belgeler var?",
        "En son yüklenen belge hangisi?",
        "Elimizde hangi belgeler var?",
        "Neye erişebiliyorsun?",
        "What documents do you have?",
        "List my documents",
    ],
)
def test_a_question_about_the_collection_is_recognised(message: str) -> None:
    assert about_library(message)


@pytest.mark.parametrize(
    "message",
    [
        "Başvuru için hangi belgeler gereklidir?",
        "Bu dosyada ne var?",
        "Bütçede neler var?",
        "Arşivde ne kadar süre saklanır?",
        "Toplantıya kaç belge sunuldu?",
        "Kararda hangi belgeler istenmiş?",
        "Meclis kaç üyeden oluşur?",
    ],
)
def test_a_question_to_the_documents_is_not(message: str) -> None:
    assert not about_library(message)


def test_no_golden_question_is_taken_for_one_about_the_collection() -> None:
    questions = [
        json.loads(line)["question"]
        for name in ("questions.jsonl", "paraphrased.jsonl")
        for line in (GOLDEN / name).read_text(encoding="utf-8").splitlines()
    ]
    assert len(questions) > 400
    assert [q for q in questions if about_library(q)] == []


async def test_a_question_about_the_collection_is_answered_from_its_list() -> None:
    chat = StandInChat("İki klasörde iki belgeniz var: bütçe kararnamesi ve kadro cetveli.")
    source = answerer([hit("Kurul 7 üyedir.")], chat)
    events = await events_of(source, "Belgelerin içerisinde neler var?")
    assert source._search.queries == []  # type: ignore[attr-defined]
    answer = final(events)
    assert (answer.status, answer.kind, answer.citations) == ("answered", "library", [])
    system = chat.calls[0][0].content
    assert "toplam 2 (1 hazır, 1 hazırlanıyor, 0 okunamadı)" in system
    assert "- Mali İşler / Bütçe 2026: 1 belge" in system
    assert (
        "2026 Bütçe Kararnamesi | Mali İşler / Bütçe 2026 | PDF, 48 sayfa | 2 Ekim 2026" in system
    )


async def test_conversation_knows_what_the_user_may_read() -> None:
    chat = StandInChat("Merhaba! İki klasördeki belgelerinize erişebiliyorum.")
    answer = final(await events_of(answerer([], chat), "Selam"))
    assert answer.kind == "conversation"
    assert "2 belge, 2 klasörde (Mali İşler (1), Mali İşler / Bütçe 2026 (1))" in (
        chat.calls[0][0].content
    )


def test_a_long_collection_says_its_list_is_cut_and_an_empty_one_says_so() -> None:
    more = Overview(LIBRARY.folders, LIBRARY.newest, total=250, ready=240, failed=3)
    assert "(Listede yalnızca en yeni 2 belge var.)" in describe(more)
    assert "7 hazırlanıyor" in describe(more)
    empty = Overview([], [], total=0, ready=0, failed=0)
    assert describe(empty) == "Kullanıcının erişebildiği hiçbir belge yok."
    assert summary(None) == ""
