"""Conversations on PostgreSQL: turns stored and audited, owned by their user, cancelled when
closed, their sources read again through the permission filter, and the streaming endpoint.

Documents are ingested for real (as in test_search.py) with stand-in models; the chat model is
a stand-in too (tests/test_chat.py covers the answering rules themselves).
"""

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Iterator, Mapping, Sequence
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any, Literal

import pytest
from fastapi.testclient import TestClient

from synapse import accounts_cli
from synapse.api.app import create_app
from synapse.api.deps import CLIENT_HEADER, CSRF_HEADER
from synapse.chat.public import (
    Answer,
    Answerer,
    Asker,
    ClassicChatDisabledError,
    ConversationNotFoundError,
    Conversations,
    Sources,
    Started,
)
from synapse.kernel.database import Database
from synapse.knowledge.public import Search
from synapse.models.public import ChatDelta, ChatMessage, ChatReply
from tests.db.conftest import TestDatabase
from tests.db.test_ingest_pipeline import PASSWORD, World, make_world
from tests.db.test_search import BagOfWords, Editor, Prefers, ingest

COUNCIL = "Belediye meclisi 7 üyeden oluşur ve 2026/35 sayılı kararı oybirliğiyle kabul etti."


@dataclass
class ScriptedChat:
    answer: str = "Meclis 7 üyeden oluşur."
    rewrite: str = ""
    # The reply in conversation (asked without a schema).
    reply: str = "Merhaba! Belgelerinizle ilgili ne sormak istersiniz?"
    calls: list[list[ChatMessage]] = field(default_factory=list)

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        schema: Mapping[str, Any] | None = None,
        max_tokens: int = 1024,
    ) -> ChatReply:
        self.calls.append(list(messages))
        return ChatReply(json.dumps({"question": self.rewrite}))

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        schema: Mapping[str, Any] | None = None,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[ChatDelta | ChatReply]:
        self.calls.append(list(messages))
        reply = {"answer": [{"text": self.answer, "sources": [1]}], "sufficient": True}
        content = self.reply if schema is None else json.dumps(reply, ensure_ascii=False)
        for start in range(0, len(content), 10):
            yield ChatDelta(content[start : start + 10])
        yield ChatReply(content)


@pytest.fixture(scope="module")
def world(test_database: TestDatabase, tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    yield from make_world(test_database, tmp_path_factory)


def sign_in(world: World, role: Literal["editor", "member"] = "editor") -> Iterator[Editor]:
    email = f"asker-{uuid.uuid4().hex[:8]}@example.org"
    user_id = accounts_cli.create_user(
        world.api, email=email, display_name="Asker", role=role, locale="tr", password=PASSWORD
    )
    with TestClient(create_app(world.api), base_url="https://testserver") as client:
        body = client.post(
            "/api/auth/login",
            json={"email": email, "password": PASSWORD},
            headers={CLIENT_HEADER: "web"},
        ).json()
        client.headers[CSRF_HEADER] = body["csrf_token"]
        yield Editor(client, user_id)


@pytest.fixture
def editor(world: World) -> Iterator[Editor]:
    yield from sign_in(world)


@pytest.fixture
def stranger(world: World) -> Iterator[Editor]:
    yield from sign_in(world, role="member")


@pytest.fixture
async def database(world: World) -> AsyncIterator[Database]:
    db = Database(world.api.database("test-chat"), max_size=2)
    await db.open()
    yield db
    await db.close()


def conversations(
    world: World, database: Database, chat: ScriptedChat, *, classic: bool = True
) -> Conversations:
    search = Search(
        database, tenant_id=world.tenant_id, embedder=BagOfWords(), reranker=Prefers("meclis")
    )
    answerer = Answerer(search, chat, refuse_below=-1.0)
    return Conversations(database, tenant_id=world.tenant_id, answerer=answerer, classic=classic)


async def ask(
    service: Conversations, user: uuid.UUID, question: str, conversation: uuid.UUID | None = None
) -> list[object]:
    return [e async for e in service.ask(Asker(user, "192.0.2.7"), question, conversation)]


def turn_row(world: World, conversation: uuid.UUID, ordinal: int) -> dict[str, Any]:
    row = world.db.execute(
        "SELECT status, question, query, answer, sources, citations, details, finished_at "
        "FROM synapse.conversation_turns WHERE conversation_id = %s AND ordinal = %s",
        (conversation, ordinal),
    ).fetchone()
    assert row is not None
    names = ("status", "question", "query", "answer", "sources", "citations", "details", "done")
    return dict(zip(names, row, strict=True))


def audited(world: World, conversation: uuid.UUID) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (action, outcome, details)
        for action, outcome, details in world.db.execute(
            "SELECT action, outcome, details FROM synapse.audit_events "
            "WHERE target_id = %s ORDER BY seq",
            (str(conversation),),
        ).fetchall()
    ]


async def test_a_question_is_answered_stored_and_audited(
    world: World, editor: Editor, database: Database
) -> None:
    (document,) = await asyncio.to_thread(ingest, world, editor, COUNCIL)
    chat = ScriptedChat()
    events = await ask(conversations(world, database, chat), editor.user_id, "Meclis kaç üyeli?")
    started = events[0]
    assert isinstance(started, Started) and started.ordinal == 1
    assert isinstance(events[1], Sources) and not events[1].ranked
    assert isinstance(events[2], Sources) and events[2].ranked
    answer = events[-1]
    assert isinstance(answer, Answer)
    assert (answer.status, answer.text, answer.citations) == (
        "answered",
        "Meclis 7 üyeden oluşur. [1]",
        [1],
    )

    row = turn_row(world, started.conversation_id, 1)
    assert (row["status"], row["question"], row["query"]) == (
        "answered",
        "Meclis kaç üyeli?",
        "Meclis kaç üyeli?",
    )
    assert row["answer"] == "Meclis 7 üyeden oluşur. [1]"
    assert row["citations"] == [1]
    assert [s["document_id"] for s in row["sources"]] == [document["id"]]
    assert "text" not in row["sources"][0]  # references only
    assert row["details"]["checked"]["claims"] == ["7"]
    assert row["done"] is not None

    ((action, outcome, details),) = audited(world, started.conversation_id)
    assert (action, outcome) == ("chat.question", "success")
    assert details["question"] == "Meclis kaç üyeli?"
    assert details["retrieved"] == details["cited"] == [document["id"]]
    assert len(details["answer_sha256"]) == 64
    assert "7 üyeden" not in json.dumps(details)  # the answer itself is not in the log


async def test_a_greeting_is_stored_as_conversation_without_sources(
    world: World, editor: Editor, database: Database
) -> None:
    await asyncio.to_thread(ingest, world, editor, COUNCIL)
    service = conversations(world, database, ScriptedChat())
    first = await ask(service, editor.user_id, "Meclis kaç üyeli?")
    assert isinstance(first[0], Started)
    conversation = first[0].conversation_id
    events = await ask(service, editor.user_id, "Teşekkürler!", conversation)
    assert not any(isinstance(event, Sources) for event in events)
    answer = events[-1]
    assert isinstance(answer, Answer)
    assert (answer.status, answer.kind) == ("answered", "conversation")

    row = world.db.execute(
        "SELECT kind, status, answer, sources, citations FROM synapse.conversation_turns "
        "WHERE conversation_id = %s AND ordinal = 2",
        (conversation,),
    ).fetchone()
    assert row == (
        "conversation",
        "answered",
        "Merhaba! Belgelerinizle ilgili ne sormak istersiniz?",
        [],
        [],
    )
    view = await service.get(editor.user_id, conversation)
    assert [t.kind for t in view.turns] == ["documents", "conversation"]
    *_, (action, outcome, details) = audited(world, conversation)
    assert (action, outcome, details["kind"]) == ("chat.question", "success", "conversation")


async def test_a_classic_conversation_is_listed_apart_and_can_be_turned_off(
    world: World, editor: Editor, database: Database
) -> None:
    service = conversations(world, database, ScriptedChat(reply="İşte taslak."))
    asker = Asker(editor.user_id, "192.0.2.7")
    events = [e async for e in service.ask(asker, "Bir e-posta yaz", mode="classic")]
    started = events[0]
    assert isinstance(started, Started)
    answer = events[-1]
    assert isinstance(answer, Answer)
    assert (answer.status, answer.kind, answer.text) == ("answered", "general", "İşte taslak.")
    classic = [c.id for c in await service.list(editor.user_id, "classic")]
    corporate = [c.id for c in await service.list(editor.user_id, "corporate")]
    assert started.conversation_id in classic and started.conversation_id not in corporate
    view = await service.get(editor.user_id, started.conversation_id)
    assert view.mode == "classic"
    # A conversation keeps its mode, whatever a later question asks for.
    again = [
        e async for e in service.ask(asker, "Daha kısa", started.conversation_id, mode="corporate")
    ]
    assert isinstance(again[-1], Answer) and again[-1].kind == "general"

    closed = conversations(world, database, ScriptedChat(), classic=False)
    with pytest.raises(ClassicChatDisabledError):
        await ask_in(closed, asker, "Merhaba", None, "classic")
    with pytest.raises(ClassicChatDisabledError):
        await ask_in(closed, asker, "Merhaba", started.conversation_id, "corporate")


async def ask_in(
    service: Conversations,
    asker: Asker,
    question: str,
    conversation: uuid.UUID | None,
    mode: Literal["corporate", "classic"],
) -> list[object]:
    return [e async for e in service.ask(asker, question, conversation, mode=mode)]


async def test_a_follow_up_continues_with_its_history(
    world: World, editor: Editor, database: Database
) -> None:
    await asyncio.to_thread(ingest, world, editor, COUNCIL)
    chat = ScriptedChat(rewrite="Meclis kararı kaç sayılıdır?", answer="2026/35 sayılıdır.")
    service = conversations(world, database, chat)
    first = await ask(service, editor.user_id, "Meclis kaç üyeli?")
    assert isinstance(first[0], Started)
    conversation = first[0].conversation_id
    events = await ask(service, editor.user_id, "Kararı kaç sayılı?", conversation)
    assert events[0] == Started(conversation, 2)
    rewrite = chat.calls[1]
    assert "Soru: Meclis kaç üyeli?" in rewrite[1].content
    assert turn_row(world, conversation, 2)["query"] == "Meclis kararı kaç sayılıdır?"

    view = await service.get(editor.user_id, conversation)
    assert [t.ordinal for t in view.turns] == [1, 2]
    assert view.turns[1].answer == "2026/35 sayılıdır. [1]"
    assert view.turns[1].sources[0].text is not None
    assert next(c.id for c in await service.list(editor.user_id)) == conversation


async def test_another_users_conversation_is_not_found(
    world: World, editor: Editor, stranger: Editor, database: Database
) -> None:
    await asyncio.to_thread(ingest, world, editor, COUNCIL)
    service = conversations(world, database, ScriptedChat())
    first = await ask(service, editor.user_id, "Meclis kaç üyeli?")
    assert isinstance(first[0], Started)
    conversation = first[0].conversation_id
    with pytest.raises(ConversationNotFoundError):
        await ask(service, stranger.user_id, "Peki ya karar?", conversation)
    with pytest.raises(ConversationNotFoundError):
        await service.get(stranger.user_id, conversation)
    with pytest.raises(ConversationNotFoundError):
        await service.rename(stranger.user_id, conversation, "Benim")
    with pytest.raises(ConversationNotFoundError):
        await service.feedback(stranger.user_id, conversation, 1, "invented")
    with pytest.raises(ConversationNotFoundError):
        await service.delete(Asker(stranger.user_id, None), conversation)
    assert await service.list(stranger.user_id) == []
    assert len((await service.get(editor.user_id, conversation)).turns) == 1


async def test_closing_the_stream_cancels_the_turn(
    world: World, editor: Editor, database: Database
) -> None:
    await asyncio.to_thread(ingest, world, editor, COUNCIL)
    service = conversations(world, database, ScriptedChat())
    conversation = None
    async with aclosing(service.ask(Asker(editor.user_id, None), "Meclis kaç üyeli?")) as events:
        async for event in events:
            if isinstance(event, Started):
                conversation = event.conversation_id
            if isinstance(event, Sources):
                break
    assert conversation is not None
    row = turn_row(world, conversation, 1)
    assert (row["status"], row["answer"], row["done"] is not None) == ("cancelled", None, True)
    assert len(row["sources"]) == 1  # what had been found is kept
    ((action, outcome, details),) = audited(world, conversation)
    assert (action, outcome, details["status"]) == ("chat.question", "failure", "cancelled")


async def test_a_failure_fails_the_turn(world: World, editor: Editor, database: Database) -> None:
    class Broken(ScriptedChat):
        async def stream(self, *args: Any, **kwargs: Any) -> AsyncGenerator[ChatDelta | ChatReply]:
            raise RuntimeError("bug")
            yield  # pragma: no cover

    await asyncio.to_thread(ingest, world, editor, COUNCIL)
    service = conversations(world, database, Broken())
    seen: list[object] = []
    with pytest.raises(RuntimeError, match="bug"):
        async for event in service.ask(Asker(editor.user_id, None), "Meclis kaç üyeli?"):
            seen.append(event)
    assert isinstance(seen[0], Started)
    row = turn_row(world, seen[0].conversation_id, 1)
    assert row["status"] == "failed"
    assert row["details"]["error"] == "internal_error"


async def test_sources_no_longer_readable_come_back_without_text(
    world: World, editor: Editor, database: Database
) -> None:
    (document,) = await asyncio.to_thread(ingest, world, editor, COUNCIL)
    service = conversations(world, database, ScriptedChat())
    first = await ask(service, editor.user_id, "Meclis kaç üyeli?")
    assert isinstance(first[0], Started)
    conversation = first[0].conversation_id
    deleted = await asyncio.to_thread(editor.client.delete, f"/api/documents/{document['id']}")
    assert deleted.status_code == 204
    (turn,) = (await service.get(editor.user_id, conversation)).turns
    (source,) = turn.sources
    assert (source.text, source.title) == (None, "")
    assert turn.answer == "Meclis 7 üyeden oluşur. [1]"  # the user's own history


async def test_rename_feedback_and_delete(world: World, editor: Editor, database: Database) -> None:
    await asyncio.to_thread(ingest, world, editor, COUNCIL)
    service = conversations(world, database, ScriptedChat())
    first = await ask(service, editor.user_id, "Meclis   kaç\nüyeli?")
    assert isinstance(first[0], Started)
    conversation = first[0].conversation_id
    assert (await service.list(editor.user_id))[0].title == "Meclis kaç üyeli?"
    await service.rename(editor.user_id, conversation, "Meclis")
    await service.feedback(editor.user_id, conversation, 1, "helpful")
    view = await service.get(editor.user_id, conversation)
    assert (view.title, view.turns[0].feedback) == ("Meclis", "helpful")
    with pytest.raises(ConversationNotFoundError):
        await service.feedback(editor.user_id, conversation, 9, "helpful")
    await service.delete(Asker(editor.user_id, None), conversation)
    with pytest.raises(ConversationNotFoundError):
        await service.get(editor.user_id, conversation)
    assert [a for a, _, _ in audited(world, conversation)] == [
        "chat.question",
        "chat.conversation.delete",
    ]


def events_of(body: str) -> list[tuple[str, dict[str, Any]]]:
    found = []
    for block in body.strip().split("\n\n"):
        name, data = block.split("\n")
        found.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return found


def test_the_endpoints_stream_answers_and_manage_conversations(
    world: World, editor: Editor
) -> None:
    ingest(world, editor, COUNCIL)
    client = editor.client
    app: Any = client.app
    # The app's own pool: it lives on the event loop the test client runs the app on.
    app.state.conversations = conversations(world, app.state.database, ScriptedChat())

    response = client.post("/api/chat", json={"question": "Meclis kaç üyeli?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = events_of(response.text)
    names = [name for name, _ in events]
    assert names[:4] == ["turn", "sources", "sources", "generating"]
    assert names[-1] == "answer" and "delta" in names
    turn = events[0][1]
    assert turn["ordinal"] == 1
    assert events[1][1]["ranked"] is False and events[2][1]["ranked"] is True
    (source,) = events[2][1]["sources"]
    assert (source["number"], source["page_start"]) == (1, 1)
    assert "".join(d["text"] for n, d in events if n == "delta") == "Meclis 7 üyeden oluşur. [1]"
    assert events[-1][1] == {
        "status": "answered",
        "text": "Meclis 7 üyeden oluşur. [1]",
        "citations": [1],
        "error": None,
        "stripped": 0,
        "kind": "documents",
    }

    conversation = turn["conversation_id"]
    assert client.get("/api/auth/session").json()["features"] == {"classic_chat": True}
    assert client.get("/api/conversations?mode=classic").json() == []
    listed = client.get("/api/conversations").json()
    assert listed[0]["id"] == conversation
    detail = client.get(f"/api/conversations/{conversation}").json()
    assert detail["turns"][0]["sources"][0]["text"] is not None
    assert (
        client.patch(f"/api/conversations/{conversation}", json={"title": " Yeni "}).status_code
        == 204
    )
    assert client.get(f"/api/conversations/{conversation}").json()["title"] == "Yeni"
    assert (
        client.patch(f"/api/conversations/{conversation}", json={"title": "  "}).status_code == 422
    )
    feedback = f"/api/conversations/{conversation}/turns/1/feedback"
    assert client.put(feedback, json={"kind": "wrong_source"}).status_code == 204
    assert client.put(feedback, json={"kind": "nonsense"}).status_code == 422
    assert client.put(feedback, json={"kind": None}).status_code == 204

    assert client.post("/api/chat", json={"question": "  "}).status_code == 422
    unknown = {"question": "Soru?", "conversation_id": str(uuid.uuid4())}
    assert client.post("/api/chat", json=unknown).json() == {"error": "not_found"}
    assert client.get(f"/api/conversations/{uuid.uuid4()}").status_code == 404
    assert client.delete(f"/api/conversations/{conversation}").status_code == 204
    assert client.delete(f"/api/conversations/{conversation}").status_code == 404


def test_without_a_chat_model_the_answer_fails_after_its_sources(
    world: World, editor: Editor
) -> None:
    ingest(world, editor, COUNCIL)
    events = events_of(editor.client.post("/api/chat", json={"question": "Meclis?"}).text)
    assert [n for n, _ in events] == ["turn", "sources", "sources", "answer"]
    assert (events[-1][1]["status"], events[-1][1]["error"]) == ("failed", "chat_unconfigured")


def test_the_viewer_reads_a_page_with_its_chunks_and_audits_it(
    world: World, editor: Editor, stranger: Editor
) -> None:
    (document,) = ingest(world, editor, COUNCIL)
    path = f"/api/documents/{document['id']}/versions/1/pages/1"
    page = editor.client.get(path).json()
    assert (page["number"], page["pages"], page["version"], page["text_source"]) == (
        1,
        1,
        1,
        "layer",
    )
    assert "7 üyeden" in page["text"]
    assert page["media_type"].endswith("wordprocessingml.document")
    ((chunk,),) = [page["chunks"]]
    assert (chunk["ordinal"], chunk["page_start"]) == (0, 1)
    assert "2026/35" in chunk["text"]
    assert editor.client.get(path.replace("pages/1", "pages/2")).status_code == 404
    assert stranger.client.get(path).json() == {"error": "not_found"}
    views = world.db.execute(
        "SELECT details FROM synapse.audit_events WHERE action = 'kb.document.view' "
        "AND target_id = %s",
        (document["id"],),
    ).fetchall()
    assert [row[0] for row in views] == [{"version": 1, "page": 1}]
