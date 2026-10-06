"""The operations page's figures and the record of maintenance runs, against the real database,
queue and roles."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pyotp
import pytest
from fastapi.testclient import TestClient

from synapse import accounts_cli
from synapse.api.app import create_app
from synapse.api.deps import CLIENT_HEADER, CSRF_HEADER
from synapse.cli import main
from synapse.kernel.config import get_settings
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


@pytest.fixture(scope="module")
def world(test_database: TestDatabase, tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    yield from make_world(test_database, tmp_path_factory)


@pytest.fixture
def editor(world: World) -> Iterator[TestClient]:
    yield from signed_in_editor(world)


@pytest.fixture(scope="module")
def admin(world: World) -> Iterator[TestClient]:
    """An administrator, signed in once with the TOTP they enrol (administrators must)."""
    email = f"admin-{uuid.uuid4().hex[:6]}@example.org"
    accounts_cli.create_user(
        world.api, email=email, display_name="Admin", role="admin", locale="en", password=PASSWORD
    )
    with TestClient(create_app(world.api), base_url="https://testserver") as client:
        body = client.post(
            "/api/auth/login",
            json={"email": email, "password": PASSWORD},
            headers={CLIENT_HEADER: "web"},
        ).json()
        csrf = {CSRF_HEADER: body["csrf_token"]}
        secret = client.post("/api/auth/mfa/totp/enroll", headers=csrf).json()["secret"]
        done = client.post(
            "/api/auth/mfa/totp/confirm", json={"code": pyotp.TOTP(secret).now()}, headers=csrf
        ).json()
        assert done["auth_level"] == "full", done
        client.headers[CSRF_HEADER] = done["csrf_token"]
        yield client


def page(admin: TestClient) -> dict[str, Any]:
    response = admin.get("/api/admin/operations")
    assert response.status_code == 200, response.json()
    body: dict[str, Any] = response.json()
    return body


def test_the_page_counts_documents_pages_queues_and_storage(
    world: World, admin: TestClient, editor: TestClient
) -> None:
    kept_bytes = samples.pdf("Karar 2026/50 kabul edildi.")
    upload(editor, kept_bytes, "kept.pdf")
    run_worker(world)
    gone_bytes = samples.word()
    gone = upload(editor, gone_bytes, "gone.docx")
    assert editor.delete(f"/api/documents/{gone['id']}").status_code == 204

    body = page(admin)
    assert body["documents"] == {"parsed": 1}
    assert body["deleted_waiting"] == 1
    assert body["retryable"] == 0
    assert body["pages"]["total"] >= 1
    assert body["pages"]["read_by_ocr"] == 0
    assert body["pages"]["waiting_for_ocr"] == 0
    # the deleted document's parse job and its purge, both waiting
    assert body["queues"] == [
        {"queue": "ingest", "waiting": 1, "running": 0, "failed": 0},
        {"queue": "maintenance", "waiting": 1, "running": 0, "failed": 0},
    ]
    storage = body["storage"]
    assert storage["files_bytes"] == len(kept_bytes) + len(gone_bytes)
    assert storage["database_bytes"] > 0
    assert 0 < storage["disk_free_bytes"] <= storage["disk_total_bytes"]
    services = {service["name"]: service for service in body["services"]}
    assert services["database"]["ok"]
    # no model server is configured in the tests, and no worker or scheduler is running
    assert set(services) == {"database", "worker", "scheduler"}
    assert body["runs"] == {"latest": {}, "latest_ok": {}}
    assert body["problems"] == {}


def test_a_running_process_is_seen_by_its_connections(world: World, admin: TestClient) -> None:
    worker = world.worker.database(application_name="synapse-worker")
    with psycopg.connect(worker.conninfo()), psycopg.connect(worker.conninfo()):
        services = {service["name"]: service for service in page(admin)["services"]}
    # another role's session shows its name, though not its queries
    assert services["worker"] == {"name": "worker", "ok": True, "connections": 2}
    assert services["scheduler"] == {"name": "scheduler", "ok": False, "connections": 0}


def test_a_broken_invariant_shows_as_a_problem(
    world: World, admin: TestClient, editor: TestClient
) -> None:
    document = upload(editor, samples.pdf("Karar 2026/51 kabul edildi."), "broken.pdf")
    run_worker(world)
    # marked ready though its chunks have no vectors
    world.db.execute(
        "UPDATE synapse.document_versions SET status = 'ready' WHERE id = %s",
        (document["version_id"],),
    )
    try:
        problems = page(admin)["problems"]
    finally:
        world.db.execute(
            "UPDATE synapse.document_versions SET status = 'parsed' WHERE id = %s",
            (document["version_id"],),
        )
    assert list(problems) == ["ready_chunks_without_vectors"]
    assert problems["ready_chunks_without_vectors"] > 0


def test_runs_on_the_host_are_recorded_through_the_command_line(
    world: World,
    admin: TestClient,
    test_database: TestDatabase,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    api = test_database.settings("synapse_api")
    for name, value in {
        "SYNAPSE_DB_HOST": api.host,
        "SYNAPSE_DB_PORT": str(api.port),
        "SYNAPSE_DB_NAME": api.dbname,
        "SYNAPSE_DB_USER": api.user,
        "SYNAPSE_DB_PASSWORD_FILE": str(api.password_file),
        "SYNAPSE_TENANT_ID": str(world.tenant_id),
        "SYNAPSE_LOG_FORMAT": "console",
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    yesterday = datetime.now(UTC) - timedelta(days=1)

    def record(*options: str, started: datetime) -> int:
        finished = started + timedelta(minutes=3)
        times = ["--started", started.isoformat(), "--finished", finished.isoformat()]
        return main(["operations", "record", "--kind", "backup", *times, *options])

    try:
        assert record("--ok", "--details", '{"snapshot": "4f3c2b1a"}', started=yesterday) == 0
        assert (
            record(
                "--failed",
                "--details",
                '{"error": "disk full"}',
                started=yesterday + timedelta(days=1),
            )
            == 0
        )
        naive = ["--started", "2026-10-06T02:30:00", "--finished", "2026-10-06T02:33:00"]
        assert main(["operations", "record", "--kind", "backup", "--ok", *naive]) == 1
        assert "offset from UTC" in capsys.readouterr().err
        unknown = ["--started", yesterday.isoformat(), "--finished", yesterday.isoformat()]
        assert main(["operations", "record", "--kind", "nightly", "--ok", *unknown]) == 1
        assert "unknown kind" in capsys.readouterr().err
    finally:
        get_settings.cache_clear()

    runs = page(admin)["runs"]
    assert runs["latest"]["backup"]["ok"] is False
    assert runs["latest"]["backup"]["details"] == {"error": "disk full"}
    assert runs["latest_ok"]["backup"]["details"] == {"snapshot": "4f3c2b1a"}


def test_processing_that_stopped_on_an_error_is_done_again(
    world: World, admin: TestClient, editor: TestClient
) -> None:
    crashed = upload(editor, samples.pdf("Karar 2026/52 kabul edildi."), "crashed.pdf")
    locked = upload(editor, samples.pdf("Karar 2026/53 kabul edildi."), "locked.pdf")
    run_worker(world)
    # one as if the worker had crashed on it after every retry, one the parser cannot read
    for document, failure in ((crashed, "internal_error"), (locked, "encrypted")):
        world.db.execute(
            "UPDATE synapse.document_versions SET status = 'failed', failure = %s WHERE id = %s",
            (failure, document["version_id"]),
        )
    assert page(admin)["retryable"] == 1
    status = (
        "SELECT status, failure, (SELECT count(*) FROM synapse.document_pages p "
        "WHERE p.version_id = v.id) FROM synapse.document_versions v WHERE v.id = %s"
    )
    locked_before = world.db.execute(status, (locked["version_id"],)).fetchone()

    response = admin.post("/api/admin/operations/retry")
    assert response.status_code == 200, response.json()
    assert response.json() == {"reprocessing": 1, "embedding": 0}
    assert world.db.execute(status, (crashed["version_id"],)).fetchone() == ("queued", None, 0)
    run_worker(world)
    done = world.db.execute(status, (crashed["version_id"],)).fetchone()
    assert done is not None
    assert done[:2] == ("parsed", None)
    assert done[2] >= 1
    # a file that cannot be read would fail the same way again: left as it was
    assert world.db.execute(status, (locked["version_id"],)).fetchone() == locked_before
    assert page(admin)["retryable"] == 0
    event = world.db.execute(
        "SELECT details FROM synapse.audit_events WHERE tenant_id = %s "
        "AND action = 'ops.documents.retry' ORDER BY seq DESC LIMIT 1",
        (world.tenant_id,),
    ).fetchone()
    assert event == ({"reprocessing": 1, "embedding": 0},)


def test_only_administrators_see_the_page(editor: TestClient) -> None:
    assert editor.get("/api/admin/operations").json() == {"error": "forbidden"}
    assert editor.post("/api/admin/operations/retry").json() == {"error": "forbidden"}
