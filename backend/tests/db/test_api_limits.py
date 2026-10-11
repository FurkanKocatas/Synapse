"""Per-user limits through the API (api/limits.py): a third question at once, a twenty-first
search in a minute and a hundred-and-first upload in an hour are refused with 429 and a
Retry-After, before anything is stored or read. Each signed-in test client runs an app of its
own, so the counts start at nothing for each test."""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx2
import pytest

from synapse.api.limits import QUESTIONS_AT_ONCE, SEARCHES, UPLOADS, UserLimits
from tests import knowledge_samples as samples
from tests.db.conftest import TestDatabase
from tests.db.test_chat import ScriptedChat, conversations, sign_in
from tests.db.test_ingest_pipeline import World, make_world
from tests.db.test_search import Editor


@pytest.fixture(scope="module")
def world(test_database: TestDatabase, tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    yield from make_world(test_database, tmp_path_factory)


@pytest.fixture
def editor(world: World) -> Iterator[Editor]:
    yield from sign_in(world)


def limits(editor: Editor) -> UserLimits:
    app: Any = editor.client.app
    held: UserLimits = app.state.limits
    return held


def refused(response: httpx2.Response) -> int:
    assert response.status_code == 429, response.text
    assert response.json() == {"error": "too_many_requests"}
    seconds = int(response.headers["Retry-After"])
    assert seconds >= 1
    return seconds


def test_a_third_question_at_once_is_refused_before_it_is_stored(
    world: World, editor: Editor
) -> None:
    client = editor.client
    app: Any = client.app
    app.state.conversations = conversations(world, app.state.database, ScriptedChat())
    asked = {"question": "Meclis kaç üyeli?"}
    held = [limits(editor).question(editor.user_id) for _ in range(QUESTIONS_AT_ONCE)]
    assert refused(client.post("/api/chat", json=asked)) == 10
    assert client.get("/api/conversations").json() == []

    first = held[0]
    assert first is not None
    first.release()
    # A question refused for another reason gives its slot back, as an answered one does.
    elsewhere = {**asked, "conversation_id": str(uuid.uuid4())}
    assert client.post("/api/chat", json=elsewhere).status_code == 404
    assert client.post("/api/chat", json=asked).status_code == 200
    assert len(client.get("/api/conversations").json()) == 1
    assert limits(editor).question(editor.user_id) is not None
    assert limits(editor).question(editor.user_id) is None


def test_a_twenty_first_search_in_a_minute_is_refused(editor: Editor) -> None:
    asked = {"query": "meclis kararları", "rerank": False}
    for _ in range(SEARCHES.count):
        assert editor.client.post("/api/search", json=asked).status_code == 200
    assert refused(editor.client.post("/api/search", json=asked)) <= 60


def incoming(world: World) -> set[Path]:
    return set((world.api.blob_dir / ".incoming").glob("*"))


def test_a_hundred_and_first_upload_in_an_hour_is_refused_before_it_is_read(
    world: World, editor: Editor
) -> None:
    client = editor.client
    name = f"C {uuid.uuid4().hex[:8]}"
    collection = client.post("/api/admin/collections", json={"name": name}).json()["id"]
    documents = f"/api/collections/{collection}/documents"
    data = samples.paragraphs("Belediye meclisi toplandı.")
    created = client.post(documents, params={"filename": "karar.docx"}, content=data)
    assert created.status_code == 201, created.json()
    for _ in range(UPLOADS.count - 1):
        assert limits(editor).wait(UPLOADS, editor.user_id) is None

    before = incoming(world)
    other = samples.paragraphs("Bütçe raporu.")
    assert refused(client.post(documents, params={"filename": "rapor.docx"}, content=other)) > 1
    version = f"/api/documents/{created.json()['id']}/versions"
    assert refused(client.post(version, params={"filename": "karar.docx"}, content=other)) > 1
    assert incoming(world) == before
    assert len(client.get(documents).json()) == 1
