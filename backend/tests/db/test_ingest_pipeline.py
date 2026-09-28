"""Upload to parsed text through the real queue and a real worker process role."""

import asyncio
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import psycopg
import pytest
from fastapi.testclient import TestClient

from synapse import accounts_cli, worker_cli
from synapse.api.app import create_app
from synapse.api.deps import CLIENT_HEADER, CSRF_HEADER
from synapse.jobs.queue import Job, Queue, enqueue
from synapse.kernel.config import Settings
from synapse.kernel.database import Database
from tests import knowledge_samples as samples
from tests.db.conftest import TestDatabase

PASSWORD = "a sufficiently long passphrase"


@dataclass(frozen=True)
class World:
    api: Settings
    worker: Settings
    tenant_id: uuid.UUID
    editor: str
    db: psycopg.Connection


@pytest.fixture(scope="module")
def world(test_database: TestDatabase, tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    api = test_database.settings("synapse_api")
    blobs = tmp_path_factory.mktemp("blobs")
    common = {
        "db_host": api.host,
        "db_port": api.port,
        "db_name": api.dbname,
        "csrf_key_file": test_database.secrets_dir / "csrf_key",
        "totp_key_file": test_database.secrets_dir / "totp_key",
        "log_format": "console",
        "blob_dir": blobs,
    }
    base = Settings(db_user=api.user, db_password_file=api.password_file, **common)  # type: ignore[arg-type]
    tenant_id = accounts_cli.create_tenant(base, f"ing-{uuid.uuid4().hex[:8]}", "Ingest")
    worker_role = test_database.settings("synapse_worker")
    worker = Settings(
        db_user=worker_role.user,
        db_password_file=worker_role.password_file,
        tenant_id=tenant_id,
        **common,  # type: ignore[arg-type]
    )
    editor = f"editor-{uuid.uuid4().hex[:6]}@example.org"
    settings = base.model_copy(update={"tenant_id": tenant_id})
    accounts_cli.create_user(
        settings, email=editor, display_name="Editor", role="editor", locale="en", password=PASSWORD
    )
    with test_database.admin() as db:
        yield World(settings, worker, tenant_id, editor, db)


@pytest.fixture
def editor(world: World) -> Iterator[TestClient]:
    with TestClient(create_app(world.api), base_url="https://testserver") as client:
        body = client.post(
            "/api/auth/login",
            json={"email": world.editor, "password": PASSWORD},
            headers={CLIENT_HEADER: "web"},
        ).json()
        client.headers[CSRF_HEADER] = body["csrf_token"]
        yield client


def upload(client: TestClient, data: bytes, name: str) -> dict[str, str]:
    collection = client.post(
        "/api/admin/collections", json={"name": f"C {uuid.uuid4().hex[:8]}"}
    ).json()["id"]
    response = client.post(
        f"/api/collections/{collection}/documents", params={"filename": name}, content=data
    )
    assert response.status_code == 201, response.json()
    body: dict[str, str] = response.json()
    body["collection_id"] = collection
    return body


def run_worker(world: World) -> None:
    # Other test modules leave jobs for their own tenants and blob directories; only this
    # module's jobs are this worker's business.
    world.db.execute(
        "DELETE FROM synapse.procrastinate_jobs WHERE status = 'todo' AND args->>'tenant_id' <> %s",
        (str(world.tenant_id),),
    )
    asyncio.run(worker_cli.run(world.worker, [Queue.INGEST], concurrency=2, once=True))


def version_state(world: World, version_id: str) -> tuple[str, str | None]:
    row = world.db.execute(
        "SELECT status, failure FROM synapse.document_versions WHERE id = %s", (version_id,)
    ).fetchone()
    assert row is not None
    return row[0], row[1]


def pages(world: World, version_id: str) -> list[tuple[int, str, str | None, bool, str]]:
    return [
        (number, kind, label, needs_ocr, text)
        for number, kind, label, needs_ocr, text in world.db.execute(
            "SELECT number, kind, label, needs_ocr, text FROM synapse.document_pages "
            "WHERE version_id = %s ORDER BY number",
            (version_id,),
        ).fetchall()
    ]


def test_an_upload_creates_its_job_in_the_same_transaction(
    world: World, editor: TestClient
) -> None:
    body = upload(editor, samples.pdf("Karar 2026/35 kabul edildi."), "karar.pdf")
    job = world.db.execute(
        "SELECT task_name, queue_name, lock, args FROM synapse.procrastinate_jobs "
        "WHERE args->>'version_id' = %s",
        (body["version_id"],),
    ).fetchone()
    assert job == (
        "ingest.parse_version",
        "ingest",
        f"document:{body['id']}",
        {"tenant_id": str(world.tenant_id), "version_id": body["version_id"]},
    )


async def test_a_rolled_back_transaction_leaves_no_job(
    world: World, test_database: TestDatabase
) -> None:
    marker = str(uuid.uuid4())
    database = Database(test_database.settings("synapse_api"), max_size=1)
    await database.open()
    try:
        with pytest.raises(RuntimeError):
            async with database.tenant_transaction(world.tenant_id) as connection:
                await enqueue(
                    connection, world.tenant_id, Job("x.probe", Queue.INGEST, {"marker": marker})
                )
                raise RuntimeError("the document insert failed")
    finally:
        await database.close()
    count = world.db.execute(
        "SELECT count(*) FROM synapse.procrastinate_jobs WHERE args->>'marker' = %s", (marker,)
    ).fetchone()
    assert count == (0,)


def test_the_worker_extracts_pages(world: World, editor: TestClient) -> None:
    text_pdf = upload(editor, samples.pdf("Karar 2026/35 kabul edildi ve sunuldu.", ""), "a.pdf")
    sheet = upload(editor, samples.spreadsheet(), "butce.xlsx")
    run_worker(world)

    assert version_state(world, text_pdf["version_id"]) == ("parsed", None)
    first, second = pages(world, text_pdf["version_id"])
    assert first[:4] == (1, "page", None, False)
    assert "Karar 2026/35" in first[4]
    assert second[:4] == (2, "page", None, True)  # no text: waits for OCR

    assert version_state(world, sheet["version_id"]) == ("parsed", None)
    assert [(n, kind, label) for n, kind, label, _, _ in pages(world, sheet["version_id"])] == [
        (1, "sheet", "Bütçe"),
        (2, "sheet", "Boş"),
    ]


def test_an_unreadable_file_fails_once_with_its_reason(world: World, editor: TestClient) -> None:
    broken = upload(editor, b"%PDF-1.7\n" + uuid.uuid4().bytes + b" broken", "broken.pdf")
    run_worker(world)
    assert version_state(world, broken["version_id"]) == ("failed", "unreadable")
    listed = editor.get(f"/api/collections/{broken['collection_id']}/documents").json()
    assert [(d["status"], d["failure"]) for d in listed] == [("failed", "unreadable")]
    assert pages(world, broken["version_id"]) == []
    status = world.db.execute(
        "SELECT status, attempts FROM synapse.procrastinate_jobs WHERE args->>'version_id' = %s",
        (broken["version_id"],),
    ).fetchone()
    # Ran once and finished: a permanent failure is not retried.
    assert status == ("succeeded", 1)


def test_a_document_deleted_before_parsing_is_skipped(world: World, editor: TestClient) -> None:
    doomed = upload(editor, samples.word(), "silinecek.docx")
    assert editor.delete(f"/api/documents/{doomed['id']}").status_code == 204
    run_worker(world)
    assert version_state(world, doomed["version_id"]) == ("queued", None)
    assert pages(world, doomed["version_id"]) == []
