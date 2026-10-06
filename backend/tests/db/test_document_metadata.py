"""A document's metadata against the real database: suggested when a version is read, set by a
person through the API, and never suggested over what a person set."""

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from synapse import accounts_cli
from synapse.api.app import create_app
from synapse.api.deps import CLIENT_HEADER, CSRF_HEADER
from synapse.kernel.database import Database
from synapse.knowledge.metadata import apply_suggestions
from tests import knowledge_samples as samples
from tests.db.conftest import TestDatabase
from tests.db.test_ingest_pipeline import (
    PASSWORD,
    World,
    make_world,
    run_worker,
    signed_in_editor,
    upload,
)

FIRST = "MECLIS KARARI\nKarar 2026/35 kabul edildi ve 15.03.2026 tarihinde sunuldu."
SECOND = "GENELGE\nGenelge 2026/40, 01.04.2026 tarihinde yayimlandi."
FIELDS = ("title", "kind", "document_date", "reference", "tags")


@pytest.fixture(scope="module")
def world(test_database: TestDatabase, tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    yield from make_world(test_database, tmp_path_factory)


@pytest.fixture
def editor(world: World) -> Iterator[TestClient]:
    yield from signed_in_editor(world)


def metadata(client: TestClient, uploaded: dict[str, str]) -> dict[str, Any]:
    listed = client.get(f"/api/collections/{uploaded['collection_id']}/documents").json()
    document = next(d for d in listed if d["id"] == uploaded["id"])
    return {name: document[name] for name in FIELDS}


def add_version(client: TestClient, document_id: str, text: str) -> str:
    response = client.post(
        f"/api/documents/{document_id}/versions",
        params={"filename": "meclis.pdf"},
        content=samples.pdf(text),
    )
    assert response.status_code == 201, response.json()
    version_id: str = response.json()["version_id"]
    return version_id


def test_suggestions_never_replace_what_a_person_set(world: World, editor: TestClient) -> None:
    uploaded = upload(editor, samples.pdf(FIRST), "meclis.pdf")
    assert metadata(editor, uploaded) == {
        "title": "meclis",
        "kind": None,
        "document_date": None,
        "reference": None,
        "tags": [],
    }
    run_worker(world)
    assert metadata(editor, uploaded) == {
        "title": "meclis",
        "kind": "Karar",
        "document_date": "2026-03-15",
        "reference": "2026/35",
        "tags": [],
    }

    changed = editor.patch(
        f"/api/documents/{uploaded['id']}",
        json={"title": " Meclis kararı ", "reference": None, "tags": ["imar", " imar", "bütçe"]},
    )
    assert changed.status_code == 204, changed.json()
    assert metadata(editor, uploaded) == {
        "title": "Meclis kararı",
        "kind": "Karar",
        "document_date": "2026-03-15",
        "reference": None,
        "tags": ["imar", "bütçe"],
    }
    editor.patch(f"/api/documents/{uploaded['id']}", json={"kind": "Meclis kararı"})

    # A new version suggests again, but only the date: a person set the kind and cleared the
    # number.
    add_version(editor, uploaded["id"], SECOND)
    run_worker(world)
    assert metadata(editor, uploaded) == {
        "title": "Meclis kararı",
        "kind": "Meclis kararı",
        "document_date": "2026-04-01",
        "reference": None,
        "tags": ["imar", "bütçe"],
    }
    events = world.db.execute(
        "SELECT details FROM synapse.audit_events WHERE tenant_id = %s "
        "AND action = 'kb.document.metadata' AND target_id = %s ORDER BY seq",
        (world.tenant_id, uploaded["id"]),
    ).fetchall()
    assert events == [({"fields": "title,tags,reference"},), ({"fields": "kind"},)]


def test_an_older_version_finishing_late_suggests_nothing(
    world: World, editor: TestClient, test_database: TestDatabase
) -> None:
    uploaded = upload(editor, samples.pdf(FIRST), "eski.pdf")
    add_version(editor, uploaded["id"], SECOND)
    run_worker(world)
    assert metadata(editor, uploaded)["kind"] == "Genelge"

    async def first_version_again() -> object:
        database = Database(test_database.settings("synapse_worker"), max_size=1)
        await database.open()
        try:
            async with database.tenant_transaction(world.tenant_id) as connection:
                return await apply_suggestions(
                    connection, uuid.UUID(uploaded["id"]), uuid.UUID(uploaded["version_id"])
                )
        finally:
            await database.close()

    assert asyncio.run(first_version_again()) is None
    assert metadata(editor, uploaded)["kind"] == "Genelge"


def test_wrong_changes_and_strangers_are_refused(world: World, editor: TestClient) -> None:
    uploaded = upload(editor, samples.pdf(FIRST), "red.pdf")
    path = f"/api/documents/{uploaded['id']}"
    for wrong in ({}, {"title": None}, {"tags": ["x" * 51]}, {"kind": "x" * 81}):
        response = editor.patch(path, json=wrong)
        assert (response.status_code, response.json()) == (422, {"error": "invalid_metadata"})
    assert editor.patch(path, json={"owner": "x"}).status_code == 422
    assert editor.patch(f"/api/documents/{uuid.uuid4()}", json={"kind": "x"}).status_code == 404

    stranger = f"member-{uuid.uuid4().hex[:6]}@example.org"
    accounts_cli.create_user(
        world.api, email=stranger, display_name="M", role="member", locale="en", password=PASSWORD
    )
    with TestClient(create_app(world.api), base_url="https://testserver") as client:
        body = client.post(
            "/api/auth/login",
            json={"email": stranger, "password": PASSWORD},
            headers={CLIENT_HEADER: "web"},
        ).json()
        client.headers[CSRF_HEADER] = body["csrf_token"]
        assert client.patch(path, json={"kind": "x"}).status_code == 404
    assert metadata(editor, uploaded)["kind"] is None
