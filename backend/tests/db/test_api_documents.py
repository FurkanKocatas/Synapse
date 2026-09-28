"""Documents end to end: upload, permissions, duplicates, versions, download and delete."""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from synapse import accounts_cli
from synapse.api.app import create_app
from synapse.api.deps import CLIENT_HEADER, CSRF_HEADER
from synapse.identity.public import Role
from synapse.kernel.config import Settings
from tests.db.conftest import TestDatabase

PASSWORD = "a sufficiently long passphrase"
PDF = b"%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\ntrailer << >>\n%%EOF\n"
OTHER_PDF = b"%PDF-1.7\n% a different document\n%%EOF\n"


@dataclass(frozen=True)
class World:
    settings: Settings
    editor: str
    reader: str
    stranger: str
    connection: psycopg.Connection


@pytest.fixture(scope="module")
def world(test_database: TestDatabase, tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    api = test_database.settings("synapse_api")
    base = Settings(
        db_host=api.host,
        db_port=api.port,
        db_name=api.dbname,
        db_user=api.user,
        db_password_file=api.password_file,
        csrf_key_file=test_database.secrets_dir / "csrf_key",
        totp_key_file=test_database.secrets_dir / "totp_key",
        log_format="console",
        blob_dir=tmp_path_factory.mktemp("blobs"),
        upload_max_mb=1,
    )
    tenant_id = accounts_cli.create_tenant(base, f"doc-{uuid.uuid4().hex[:8]}", "Documents")
    settings = base.model_copy(update={"tenant_id": tenant_id})
    emails: dict[str, str] = {}
    roles: dict[str, Role] = {"editor": "editor", "reader": "member", "stranger": "member"}
    for name, role in roles.items():
        emails[name] = f"{name}-{uuid.uuid4().hex[:6]}@example.org"
        accounts_cli.create_user(
            settings,
            email=emails[name],
            display_name=name.title(),
            role=role,
            locale="en",
            password=PASSWORD,
        )
    # Grants are written directly: the administration API needs an administrator's second
    # factor, and it has its own tests.
    connection = psycopg.connect(api.conninfo(), autocommit=True)
    connection.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))
    yield World(settings, emails["editor"], emails["reader"], emails["stranger"], connection)
    connection.close()


@pytest.fixture
def clients() -> Iterator[list[TestClient]]:
    opened: list[TestClient] = []
    yield opened
    for client in opened:
        client.__exit__(None, None, None)


def sign_in(world: World, email: str, clients: list[TestClient]) -> TestClient:
    client = TestClient(create_app(world.settings), base_url="https://testserver")
    client.__enter__()
    clients.append(client)
    body = client.post(
        "/api/auth/login",
        json={"email": email, "password": PASSWORD},
        headers={CLIENT_HEADER: "web"},
    ).json()
    client.headers[CSRF_HEADER] = body["csrf_token"]
    return client


def new_collection(editor: TestClient) -> str:
    created = editor.post("/api/admin/collections", json={"name": f"C {uuid.uuid4().hex[:8]}"})
    collection: str = created.json()["id"]
    return collection


def grant_read(world: World, collection: str, email: str) -> None:
    world.connection.execute(
        "INSERT INTO collection_grants (tenant_id, collection_id, principal_user_id, permission) "
        "SELECT tenant_id, %s, id, 'read' FROM users WHERE email = %s",
        (collection, email),
    )


def upload(client: TestClient, collection: str, data: bytes, name: str = "Karar 2026-35.pdf"):  # type: ignore[no-untyped-def]
    return client.post(
        f"/api/collections/{collection}/documents", params={"filename": name}, content=data
    )


def incoming_files(world: World) -> list[Path]:
    return list((world.settings.blob_dir / ".incoming").glob("*"))


def test_an_editor_uploads_and_a_reader_downloads(world: World, clients: list[TestClient]) -> None:
    editor = sign_in(world, world.editor, clients)
    collection = new_collection(editor)
    created = upload(editor, collection, PDF)
    assert created.status_code == 201, created.json()
    body = created.json()
    assert (body["version"], body["media_type"]) == (1, "application/pdf")

    grant_read(world, collection, world.reader)
    reader = sign_in(world, world.reader, clients)
    [listed] = reader.get(f"/api/collections/{collection}/documents").json()
    assert (listed["title"], listed["status"], listed["size_bytes"]) == (
        "Karar 2026-35",
        "queued",
        len(PDF),
    )
    file = reader.get(f"/api/documents/{body['id']}/versions/1/file")
    assert file.content == PDF
    assert file.headers["content-type"] == "application/pdf"
    assert file.headers["content-disposition"].startswith("attachment;")
    assert "sandbox" in file.headers["content-security-policy"]
    assert file.headers["x-content-type-options"] == "nosniff"


def test_people_without_access_see_nothing_and_store_nothing(
    world: World, clients: list[TestClient]
) -> None:
    editor = sign_in(world, world.editor, clients)
    collection = new_collection(editor)
    document = upload(editor, collection, PDF).json()["id"]
    grant_read(world, collection, world.reader)
    reader = sign_in(world, world.reader, clients)
    stranger = sign_in(world, world.stranger, clients)

    assert stranger.get(f"/api/collections/{collection}/documents").json() == []
    for client in (stranger,):
        assert client.get(f"/api/documents/{document}/versions").status_code == 404
        assert client.get(f"/api/documents/{document}/versions/1/file").status_code == 404
    # Reading is not writing: the reader cannot upload, add versions or delete.
    for client in (reader, stranger):
        assert upload(client, collection, OTHER_PDF).json() == {"error": "not_found"}
        response = client.post(
            f"/api/documents/{document}/versions", params={"filename": "x.pdf"}, content=OTHER_PDF
        )
        assert response.status_code == 404
        assert client.delete(f"/api/documents/{document}").status_code == 404
    assert incoming_files(world) == []


def test_identical_files_are_stored_once(world: World, clients: list[TestClient]) -> None:
    editor = sign_in(world, world.editor, clients)
    first, second = new_collection(editor), new_collection(editor)
    unique = PDF + uuid.uuid4().bytes
    assert upload(editor, first, unique).status_code == 201
    assert upload(editor, first, unique, "copy.pdf").json() == {"error": "duplicate_document"}
    assert upload(editor, second, unique, "elsewhere.pdf").status_code == 201
    count = world.connection.execute(
        "SELECT count(*) FROM blobs WHERE size_bytes = %s", (len(unique),)
    ).fetchone()
    assert count == (1,)
    assert incoming_files(world) == []


def test_files_are_checked_before_they_are_kept(world: World, clients: list[TestClient]) -> None:
    editor = sign_in(world, world.editor, clients)
    collection = new_collection(editor)
    cases = [
        (b"plain text, whatever the name", 415, "unknown_type"),
        (bytes.fromhex("d0cf11e0a1b11ae1") + b"\x00" * 100, 415, "legacy_office"),
        (b"", 400, "empty_file"),
        (b"%PDF-" + b"x" * (1024 * 1024), 413, "file_too_large"),
    ]
    for data, code, error in cases:
        response = upload(editor, collection, data, "report.pdf")
        assert (response.status_code, response.json()) == (code, {"error": error})
    assert editor.get(f"/api/collections/{collection}/documents").json() == []
    assert incoming_files(world) == []


def test_new_versions_and_deletion(world: World, clients: list[TestClient]) -> None:
    editor = sign_in(world, world.editor, clients)
    collection = new_collection(editor)
    document = upload(editor, collection, PDF + b"v1").json()["id"]
    added = editor.post(
        f"/api/documents/{document}/versions",
        params={"filename": "Karar 2026-35 (düzeltilmiş).pdf"},
        content=PDF + b"v2",
    )
    assert added.json()["version"] == 2
    versions = editor.get(f"/api/documents/{document}/versions").json()
    assert [(v["version"], v["filename"]) for v in versions] == [
        (2, "Karar 2026-35 (düzeltilmiş).pdf"),
        (1, "Karar 2026-35.pdf"),
    ]
    [listed] = editor.get(f"/api/collections/{collection}/documents").json()
    assert listed["latest_version"] == 2
    old = editor.get(f"/api/documents/{document}/versions/1/file")
    assert old.content == PDF + b"v1"

    assert editor.delete(f"/api/documents/{document}").status_code == 204
    assert editor.get(f"/api/collections/{collection}/documents").json() == []
    assert editor.get(f"/api/documents/{document}/versions").status_code == 404
    actions = [
        row[0]
        for row in world.connection.execute(
            "SELECT action FROM audit_events WHERE target_id = %s ORDER BY seq", (document,)
        ).fetchall()
    ]
    assert actions == ["kb.document.create", "kb.document.version", "kb.document.delete"]
