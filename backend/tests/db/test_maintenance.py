"""Purges and sweeps through the real queue, as the scheduler's own database role."""

import asyncio
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from synapse import scheduler_cli
from synapse.jobs.queue import enqueue
from synapse.kernel.config import Settings
from synapse.kernel.database import Database
from synapse.knowledge.pipeline import purge_job
from synapse.knowledge.public import LocalBlobStore, Maintenance
from tests import knowledge_samples as samples
from tests.db.conftest import TestDatabase
from tests.db.test_ingest_pipeline import (
    World,
    make_world,
    run_worker,
    signed_in_editor,
    upload,
)

DAY = timedelta(days=1)


@pytest.fixture(scope="module")
def world(test_database: TestDatabase, tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    yield from make_world(test_database, tmp_path_factory)


@pytest.fixture
def editor(world: World) -> Iterator[TestClient]:
    yield from signed_in_editor(world)


@pytest.fixture(scope="module")
def scheduler(world: World, test_database: TestDatabase) -> Settings:
    role = test_database.settings("synapse_scheduler")
    return world.worker.model_copy(
        update={"db_user": role.user, "db_password_file": role.password_file}
    )


def run_scheduler(world: World, scheduler: Settings) -> None:
    world.db.execute(
        "DELETE FROM synapse.procrastinate_jobs WHERE status = 'todo' AND args->>'tenant_id' <> %s",
        (str(world.tenant_id),),
    )
    asyncio.run(scheduler_cli.run(scheduler, once=True))


def run_task(scheduler: Settings, name: str, now: datetime | None = None) -> None:
    """One of the scheduled jobs, run now (the scheduler defers them on its cron)."""

    async def run() -> None:
        database = Database(scheduler.database(application_name="synapse-tests"), max_size=2)
        await database.open()
        try:
            maintenance = Maintenance(
                database, LocalBlobStore(scheduler.blob_dir), now=lambda: now or datetime.now(UTC)
            )
            task = next(task for task in maintenance.tasks() if task.name == name)
            assert scheduler.tenant_id is not None
            await task.run(scheduler.tenant_id, {})
        finally:
            await database.close()

    asyncio.run(run())


def count(world: World, query: str, *args: Any) -> int:
    row = world.db.execute(query, args).fetchone()
    assert row is not None
    return int(row[0])


def blob_file(world: World, scheduler: Settings, document: dict[str, str]) -> Path:
    row = world.db.execute(
        "SELECT blob_sha256 FROM synapse.document_versions WHERE id = %s",
        (document["version_id"],),
    ).fetchone()
    assert row is not None
    return LocalBlobStore(scheduler.blob_dir).path(world.tenant_id, bytes(row[0]))


def age(path: Path, by: timedelta) -> None:
    then = (datetime.now(UTC) - by).timestamp()
    os.utime(path, (then, then))


def test_a_deleted_document_is_purged_with_everything_read_from_it(
    world: World, scheduler: Settings, editor: TestClient
) -> None:
    document = upload(editor, samples.pdf("Karar 2026/40 kabul edildi."), "purge.pdf")
    run_worker(world)
    version = document["version_id"]
    assert count(
        world, "SELECT count(*) FROM synapse.document_chunks WHERE version_id = %s", version
    )
    file = blob_file(world, scheduler, document)

    assert editor.delete(f"/api/documents/{document['id']}").status_code == 204
    jobs = world.db.execute(
        "SELECT task_name, queue_name, lock, status FROM synapse.procrastinate_jobs "
        "WHERE args->>'document_id' = %s",
        (document["id"],),
    ).fetchall()
    assert jobs == [
        ("knowledge.purge_document", "maintenance", f"document:{document['id']}", "todo")
    ]
    run_scheduler(world, scheduler)

    for table, column, key in (
        ("documents", "id", document["id"]),
        ("document_versions", "document_id", document["id"]),
        ("document_pages", "version_id", version),
        ("document_chunks", "version_id", version),
        ("chunk_entities", "version_id", version),
    ):
        query = f"SELECT count(*) FROM synapse.{table} WHERE {column} = %s"  # noqa: S608
        assert count(world, query, key) == 0, table
    unnamed = (
        "SELECT count(*) FROM synapse.blobs b WHERE b.tenant_id = %s AND NOT EXISTS ("
        "SELECT 1 FROM synapse.document_versions v WHERE v.blob_sha256 = b.sha256)"
    )
    assert count(world, unnamed, world.tenant_id) == 0
    assert file.exists()  # the sweep removes files, a day after the purge
    events = world.db.execute(
        "SELECT action, details FROM synapse.audit_events WHERE target_id = %s ORDER BY seq",
        (document["id"],),
    ).fetchall()
    assert [action for action, _ in events][-2:] == ["kb.document.delete", "kb.document.purge"]
    assert events[-1][1] == {"versions": 1, "files_released": 1}
    assert editor.get(f"/api/documents/{document['id']}/versions/1/file").status_code == 404


def test_bytes_a_live_document_shares_stay(
    world: World, scheduler: Settings, editor: TestClient
) -> None:
    data = samples.pdf("Karar 2026/41 kabul edildi.")
    kept = upload(editor, data, "kept.pdf")
    gone = upload(editor, data, "gone.pdf")  # another collection: not a duplicate
    assert editor.delete(f"/api/documents/{gone['id']}").status_code == 204
    run_worker(world)
    run_scheduler(world, scheduler)
    assert count(world, "SELECT count(*) FROM synapse.documents WHERE id = %s", gone["id"]) == 0
    response = editor.get(f"/api/documents/{kept['id']}/versions/1/file")
    assert response.status_code == 200
    assert response.content == data


def test_the_purge_waits_for_the_documents_processing(
    world: World, scheduler: Settings, editor: TestClient
) -> None:
    document = upload(editor, samples.word(), "early.docx")
    assert editor.delete(f"/api/documents/{document['id']}").status_code == 204
    # the parse job, queued first under the same lock, holds the purge back
    run_scheduler(world, scheduler)
    assert count(world, "SELECT count(*) FROM synapse.documents WHERE id = %s", document["id"])
    run_worker(world)
    run_scheduler(world, scheduler)
    assert count(world, "SELECT count(*) FROM synapse.documents WHERE id = %s", document["id"]) == 0
    statuses = world.db.execute(
        "SELECT task_name, status FROM synapse.procrastinate_jobs "
        "WHERE args->>'version_id' = %s OR args->>'document_id' = %s ORDER BY id",
        (document["version_id"], document["id"]),
    ).fetchall()
    assert statuses == [
        ("ingest.parse_version", "succeeded"),
        ("knowledge.purge_document", "succeeded"),
    ]


def test_documents_deleted_without_a_purge_get_one(
    world: World, scheduler: Settings, editor: TestClient
) -> None:
    document = upload(editor, samples.word(), "old.docx")
    run_worker(world)
    assert editor.delete(f"/api/documents/{document['id']}").status_code == 204
    # as if deleted before purges existed: no job, a day ago
    world.db.execute(
        "DELETE FROM synapse.procrastinate_jobs WHERE args->>'document_id' = %s", (document["id"],)
    )
    world.db.execute(
        "UPDATE synapse.documents SET deleted_at = now() - interval '1 day' WHERE id = %s",
        (document["id"],),
    )
    run_task(scheduler, "knowledge.purge_late")
    run_task(scheduler, "knowledge.purge_late")  # one job, however often it runs
    query = (
        "SELECT count(*) FROM synapse.procrastinate_jobs "
        "WHERE task_name = 'knowledge.purge_document' AND args->>'document_id' = %s"
    )
    assert count(world, query, document["id"]) == 1
    run_scheduler(world, scheduler)
    assert count(world, "SELECT count(*) FROM synapse.documents WHERE id = %s", document["id"]) == 0


def test_the_sweep_removes_files_no_row_has_named_for_a_day(
    world: World, scheduler: Settings, editor: TestClient
) -> None:
    store = LocalBlobStore(scheduler.blob_dir)
    purged = upload(editor, samples.pdf("Karar 2026/42 kabul edildi."), "swept.pdf")
    run_worker(world)
    purged_file = blob_file(world, scheduler, purged)
    assert editor.delete(f"/api/documents/{purged['id']}").status_code == 204
    run_scheduler(world, scheduler)
    live = upload(editor, samples.pdf("Karar 2026/43 kabul edildi."), "live.pdf")
    live_file = blob_file(world, scheduler, live)
    recent = store.path(world.tenant_id, bytes(32 * [7]))  # a crash between rename and commit
    recent.parent.mkdir(parents=True, exist_ok=True)
    recent.write_bytes(b"left over")
    half = store.incoming_dir() / "dropped.part"
    half.write_bytes(b"half an upload")
    for path in (purged_file, live_file, half):
        age(path, 2 * DAY)

    run_task(scheduler, "knowledge.sweep_files")
    assert not purged_file.exists()
    assert live_file.exists()  # old, but its row names it
    assert recent.exists()  # no row, but not a day old
    assert not half.exists()
    run_task(scheduler, "knowledge.sweep_files", now=datetime.now(UTC) + 2 * DAY)
    assert not recent.exists()


def test_bytes_stored_again_after_a_purge_keep_their_file(
    world: World, scheduler: Settings, editor: TestClient
) -> None:
    data = samples.pdf("Karar 2026/44 kabul edildi.")
    first = upload(editor, data, "first.pdf")
    file = blob_file(world, scheduler, first)
    assert editor.delete(f"/api/documents/{first['id']}").status_code == 204
    run_worker(world)
    run_scheduler(world, scheduler)
    age(file, 2 * DAY)  # purged long ago, the file not swept yet
    again = upload(editor, data, "again.pdf")
    # storing the bytes again renewed the file's time, so no sweep can take it from the upload
    renewed = LocalBlobStore(scheduler.blob_dir).modified(world.tenant_id, bytes.fromhex(file.name))
    assert renewed is not None
    assert renewed > datetime.now(UTC) - timedelta(minutes=5)
    run_task(scheduler, "knowledge.sweep_files")
    assert file.exists()
    response = editor.get(f"/api/documents/{again['id']}/versions/1/file")
    assert response.content == data


def test_the_scheduler_needs_its_tenant(scheduler: Settings) -> None:
    with pytest.raises(scheduler_cli.SchedulerError, match="SYNAPSE_TENANT_ID"):
        asyncio.run(scheduler_cli.run(scheduler.model_copy(update={"tenant_id": None}), once=True))


def test_a_purge_of_a_document_that_is_gone_succeeds(world: World, scheduler: Settings) -> None:
    async def defer() -> None:
        database = Database(scheduler.database(application_name="synapse-tests"), max_size=1)
        await database.open()
        try:
            async with database.tenant_transaction(world.tenant_id) as connection:
                await enqueue(connection, world.tenant_id, purge_job(uuid.uuid4()))
        finally:
            await database.close()

    asyncio.run(defer())
    run_scheduler(world, scheduler)
    last = world.db.execute(
        "SELECT status FROM synapse.procrastinate_jobs WHERE task_name = "
        "'knowledge.purge_document' AND args->>'tenant_id' = %s ORDER BY id DESC LIMIT 1",
        (str(world.tenant_id),),
    ).fetchone()
    assert last == ("succeeded",)  # nothing left to purge is not a failure
