"""Upload to parsed text through the real queue and a real worker process role."""

import asyncio
import io
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from synapse import accounts_cli, worker_cli
from synapse.api.app import create_app
from synapse.api.deps import CLIENT_HEADER, CSRF_HEADER
from synapse.jobs.queue import Job, Queue, enqueue
from synapse.jobs.worker import BadJobError
from synapse.kernel.config import Settings
from synapse.kernel.database import Database
from synapse.knowledge.ocr import OcrError, PageReading
from synapse.knowledge.public import LightParser, LocalBlobStore, Processor, reindex
from synapse.models.public import Embedder, ModelUnavailableError
from tests import knowledge_samples as samples
from tests.db.conftest import TestDatabase

PASSWORD = "a sufficiently long passphrase"


@dataclass
class StandInReader:
    """Reads every page as the same text; the real engines run in the full-stack smoke test."""

    fail: bool = False
    name: str = "stand-in"
    read_images: list[str] = field(default_factory=list)

    def read(self, image: Path) -> PageReading:
        self.read_images.append(image.name)
        if self.fail:
            raise OcrError("tesseract failed: CalledProcessError")
        return PageReading("Karar 2026/35 okundu.", "stand-in", ("2026/36",), ("2026/35",))

    def close(self) -> None:
        pass


@dataclass
class StandInEmbedder:
    """Points each text's vector along the axis of its length; the real model runs in the
    full-stack smoke test."""

    fail: bool = False
    model: str = "bge-m3"
    dimensions: int = 1024
    texts: list[str] = field(default_factory=list)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if self.fail:
            raise ModelUnavailableError("embedding", "/tokenize: connection refused")
        self.texts.extend(texts)
        return [[1.0 if i == len(t) % self.dimensions else 0.0 for i in range(1024)] for t in texts]


@dataclass(frozen=True)
class World:
    api: Settings
    worker: Settings
    tenant_id: uuid.UUID
    editor: str
    db: psycopg.Connection


@pytest.fixture(scope="module")
def world(test_database: TestDatabase, tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    yield from make_world(test_database, tmp_path_factory)


def make_world(
    test_database: TestDatabase, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[World]:
    """A tenant of its own with an editor, the API's and the worker's settings (other test
    modules build theirs with it too)."""
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
    yield from signed_in_editor(world)


def signed_in_editor(world: World) -> Iterator[TestClient]:
    """An API client signed in as the world's editor (other test modules use it too)."""
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


def run_worker(
    world: World,
    reader: StandInReader | None = None,
    queues: Sequence[Queue] = (Queue.INGEST, Queue.OCR),
    embedder: Embedder | None = None,
) -> StandInReader:
    # Other test modules leave jobs for their own tenants and blob directories; only this
    # module's jobs are this worker's business.
    world.db.execute(
        "DELETE FROM synapse.procrastinate_jobs WHERE status = 'todo' AND args->>'tenant_id' <> %s",
        (str(world.tenant_id),),
    )
    reader = reader or StandInReader()
    # A worker run with once=True stops as soon as it finds no job, even while a running job is
    # about to enqueue the next one (parsing enqueues OCR); run again until nothing is left.
    for _ in range(5):
        asyncio.run(
            worker_cli.run(
                world.worker, queues, concurrency=2, once=True, reader=reader, embedder=embedder
            )
        )
        left = world.db.execute(
            "SELECT count(*) FROM synapse.procrastinate_jobs "
            "WHERE status = 'todo' AND queue_name = ANY(%s) AND args->>'tenant_id' = %s",
            ([q.value for q in queues], str(world.tenant_id)),
        ).fetchone()
        if left == (0,):
            return reader
    raise AssertionError("jobs still waiting after five worker runs")


def ocr_state(world: World, version_id: str) -> list[tuple[Any, ...]]:
    """(number, text, text_source, ocr_engine, extra_identifiers) per page."""
    return [
        tuple(row)
        for row in world.db.execute(
            "SELECT number, text, text_source, ocr_engine, extra_identifiers "
            "FROM synapse.document_pages WHERE version_id = %s ORDER BY number",
            (version_id,),
        ).fetchall()
    ]


def png() -> bytes:
    buffer = io.BytesIO()
    Image.new("L", (1654, 2339), 255).save(buffer, format="PNG")
    return buffer.getvalue()


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
    assert second[:4] == (2, "page", None, True)  # no text: read by OCR
    issues = world.db.execute(
        "SELECT number, quality_issue FROM synapse.document_pages WHERE version_id = %s "
        "ORDER BY number",
        (text_pdf["version_id"],),
    ).fetchall()
    assert issues == [(1, None), (2, "no_text")]

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


def test_pages_without_usable_text_are_read_by_ocr(world: World, editor: TestClient) -> None:
    scan = upload(editor, samples.pdf("Karar 2026/35 kabul edildi ve sunuldu.", ""), "scan.pdf")
    image = upload(editor, png(), "tarama.png")
    reader = run_worker(world)

    assert version_state(world, scan["version_id"]) == ("parsed", None)
    layer, read = ocr_state(world, scan["version_id"])
    assert layer[2:] == ("layer", None, [])
    assert read == (2, "Karar 2026/35 okundu.", "ocr", "stand-in", ["2026/36"])
    uncertain = world.db.execute(
        "SELECT uncertain_identifiers FROM synapse.document_pages "
        "WHERE version_id = %s AND number = 2",
        (scan["version_id"],),
    ).fetchone()
    assert uncertain == (["2026/35"],)

    assert version_state(world, image["version_id"]) == ("parsed", None)
    assert ocr_state(world, image["version_id"]) == [
        (1, "Karar 2026/35 okundu.", "ocr", "stand-in", ["2026/36"])
    ]
    # Each image was deleted once read; only the two scanned pages were read.
    assert sorted(reader.read_images) == ["image.png", "page-00002.png"]


def test_a_page_the_engine_fails_on_keeps_its_text(world: World, editor: TestClient) -> None:
    scan = upload(editor, samples.pdf(""), "bos.pdf")
    run_worker(world, StandInReader(fail=True))
    assert version_state(world, scan["version_id"]) == ("parsed", None)
    assert ocr_state(world, scan["version_id"]) == [(1, "", "layer", None, [])]


def test_a_retried_ocr_job_reads_only_the_pages_left(world: World, editor: TestClient) -> None:
    scan = upload(editor, samples.pdf("", ""), "iki.pdf")
    run_worker(world, queues=[Queue.INGEST])
    assert version_state(world, scan["version_id"]) == ("ocr", None)
    # As if an earlier run had read page 1 and then crashed.
    world.db.execute(
        "UPDATE synapse.document_pages SET text = 'earlier', text_source = 'ocr', "
        "ocr_engine = 'earlier' WHERE version_id = %s AND number = 1",
        (scan["version_id"],),
    )
    reader = run_worker(world, queues=[Queue.OCR])
    assert reader.read_images == ["page-00002.png"]
    assert [
        (n, text, engine) for n, text, _, engine, _ in ocr_state(world, scan["version_id"])
    ] == [
        (1, "earlier", "earlier"),
        (2, "Karar 2026/35 okundu.", "stand-in"),
    ]
    assert version_state(world, scan["version_id"]) == ("parsed", None)


def test_finished_pages_are_chunked_with_their_entities(world: World, editor: TestClient) -> None:
    text = "Karar 2026/35 kabul edildi ve 15.03.2026 tarihinde sunuldu."
    layer = upload(editor, samples.pdf(text), "k.pdf")
    scan = upload(editor, samples.pdf(""), "tarama.pdf")
    run_worker(world)

    def chunks(version_id: str) -> list[tuple[Any, ...]]:
        return [
            tuple(row)
            for row in world.db.execute(
                "SELECT ordinal, kind, text, page_start, page_end, length(content_hash) "
                "FROM synapse.document_chunks WHERE version_id = %s ORDER BY ordinal",
                (version_id,),
            ).fetchall()
        ]

    def entities(version_id: str) -> list[tuple[Any, ...]]:
        return [
            tuple(row)
            for row in world.db.execute(
                "SELECT kind, value, written FROM synapse.chunk_entities WHERE version_id = %s "
                "ORDER BY char_start",
                (version_id,),
            ).fetchall()
        ]

    assert chunks(layer["version_id"]) == [(0, "text", text, 1, 1, 32)]
    assert entities(layer["version_id"]) == [
        ("decision_number", "2026/35", "2026/35"),
        ("date", "2026-03-15", "15.03.2026"),
    ]
    # The scanned page is chunked from its OCR text, once OCR has read it.
    assert chunks(scan["version_id"]) == [(0, "text", "Karar 2026/35 okundu.", 1, 1, 32)]
    assert entities(scan["version_id"]) == [("decision_number", "2026/35", "2026/35")]
    # What the second reading found and the text lacks is searched for, never shown.
    terms = world.db.execute(
        "SELECT version_id = %s, search FROM synapse.document_chunks "
        "WHERE version_id IN (%s, %s) ORDER BY 1",
        (scan["version_id"], layer["version_id"], scan["version_id"]),
    ).fetchall()
    assert [(scanned, "2026/36" in search.split()) for scanned, search in terms] == [
        (False, False),
        (True, True),
    ]


ALL_QUEUES = (Queue.INGEST, Queue.OCR, Queue.EMBED)
TEXT = "Karar 2026/35 kabul edildi ve 15.03.2026 tarihinde sunuldu."


def vectors(world: World, version_id: str) -> list[list[float] | None]:
    rows = world.db.execute(
        "SELECT embedding::text FROM synapse.document_chunks WHERE version_id = %s "
        "ORDER BY ordinal",
        (version_id,),
    ).fetchall()
    return [
        None if text is None else [float(v) for v in text.strip("[]").split(",")]
        for (text,) in rows
    ]


def indexing(world: World, version_id: str) -> tuple[str | None, str | None]:
    row = world.db.execute(
        "SELECT context, embedded_with FROM synapse.document_versions WHERE id = %s",
        (version_id,),
    ).fetchone()
    assert row is not None
    return row[0], row[1]


def test_chunks_are_embedded_with_their_document_context(world: World, editor: TestClient) -> None:
    body = upload(editor, samples.pdf(TEXT), "meclis_kararı-2026.pdf")
    embedder = StandInEmbedder()
    run_worker(world, queues=ALL_QUEUES, embedder=embedder)

    context = f"meclis kararı 2026\n{TEXT}"
    assert version_state(world, body["version_id"]) == ("ready", None)
    assert indexing(world, body["version_id"]) == (context, "bge-m3")
    # What was embedded is the context, then the chunk as search indexes it.
    assert embedder.texts == [f"{context}\n{TEXT}"]
    (vector,) = vectors(world, body["version_id"])
    assert vector is not None
    assert len(vector) == 1024
    assert vector.index(1.0) == len(embedder.texts[0]) % 1024
    listed = editor.get(f"/api/collections/{body['collection_id']}/documents").json()
    assert [d["status"] for d in listed] == ["ready"]


def test_without_an_embedding_model_versions_stay_parsed(world: World, editor: TestClient) -> None:
    body = upload(editor, samples.pdf(TEXT), "modelsiz.pdf")
    run_worker(world, queues=ALL_QUEUES)
    assert version_state(world, body["version_id"]) == ("parsed", None)
    assert indexing(world, body["version_id"]) == (f"modelsiz\n{TEXT}", None)
    assert vectors(world, body["version_id"]) == [None]
    queued = world.db.execute(
        "SELECT count(*) FROM synapse.procrastinate_jobs WHERE task_name = 'ingest.embed_version' "
        "AND args->>'version_id' = %s",
        (body["version_id"],),
    ).fetchone()
    assert queued == (0,)


def test_a_retried_embedding_job_embeds_only_the_chunks_left(
    world: World, editor: TestClient
) -> None:
    body = upload(editor, samples.pdf(TEXT), "yarim.pdf")
    run_worker(world, queues=[Queue.INGEST], embedder=StandInEmbedder())
    assert version_state(world, body["version_id"]) == ("parsed", None)
    # As if an earlier run had embedded the chunk and then crashed before marking the version.
    world.db.execute(
        "UPDATE synapse.document_chunks "
        "SET embedding = array_fill(0.5::real, ARRAY[1024])::halfvec WHERE version_id = %s",
        (body["version_id"],),
    )
    world.db.execute(
        "UPDATE synapse.document_versions SET status = 'embedding' WHERE id = %s",
        (body["version_id"],),
    )
    embedder = StandInEmbedder()
    run_worker(world, queues=[Queue.EMBED], embedder=embedder)
    assert embedder.texts == []
    assert version_state(world, body["version_id"]) == ("ready", None)
    (vector,) = vectors(world, body["version_id"])
    assert vector == [0.5] * 1024


async def test_an_unreachable_model_leaves_the_version_parsed_and_retryable(
    world: World, editor: TestClient
) -> None:
    body = upload(editor, samples.pdf(TEXT), "erisilemez.pdf")
    await asyncio.to_thread(run_worker, world, None, [Queue.INGEST], StandInEmbedder())
    version = {"version_id": body["version_id"]}
    database = Database(world.worker.database("test-embed"), max_size=2)
    await database.open()
    try:
        failing = Processor(
            database,
            LocalBlobStore(world.worker.blob_dir),
            LightParser(),
            StandInReader(),
            StandInEmbedder(fail=True),
        )
        with pytest.raises(ModelUnavailableError):
            await failing.embed(world.tenant_id, version)
        assert version_state(world, body["version_id"]) == ("embedding", None)
        # The worker calls this after the last attempt.
        await failing.give_up_embed(world.tenant_id, version, "ModelUnavailableError")
    finally:
        await database.close()
    # Not failed: the text is there, and a later run with the model reachable finishes the job.
    assert version_state(world, body["version_id"]) == ("parsed", None)
    assert embedding_failure(world, body["version_id"]) == "model_unavailable"
    assert pages(world, body["version_id"])[0][4].startswith("Karar 2026/35")
    await asyncio.to_thread(run_worker, world, None, [Queue.EMBED], StandInEmbedder())
    assert version_state(world, body["version_id"]) == ("ready", None)
    assert embedding_failure(world, body["version_id"]) is None


def embedding_failure(world: World, version_id: str) -> str | None:
    row = world.db.execute(
        "SELECT embedding_failure FROM synapse.document_versions WHERE id = %s", (version_id,)
    ).fetchone()
    assert row is not None
    failure: str | None = row[0]
    return failure


async def test_an_embedding_job_without_a_model_is_refused(world: World) -> None:
    database = Database(world.worker.database("test-embed"), max_size=1)
    await database.open()
    try:
        processor = Processor(
            database, LocalBlobStore(world.worker.blob_dir), LightParser(), StandInReader()
        )
        with pytest.raises(BadJobError, match="no embedding model"):
            await processor.embed(world.tenant_id, {"version_id": str(uuid.uuid4())})
    finally:
        await database.close()


def embedding_jobs(world: World, version_id: str) -> int:
    row = world.db.execute(
        "SELECT count(*) FROM synapse.procrastinate_jobs WHERE task_name = 'ingest.embed_version' "
        "AND status = 'todo' AND args->>'version_id' = %s",
        (version_id,),
    ).fetchone()
    assert row is not None
    count: int = row[0]
    return count


async def test_reindex_writes_missing_terms_and_queues_embedding(
    world: World, editor: TestClient
) -> None:
    old = upload(editor, samples.pdf(TEXT), "eski.pdf")
    plain = upload(editor, samples.pdf(TEXT), "vektorsuz.pdf")
    scan = upload(editor, samples.pdf(""), "eski-tarama.pdf")
    # Without an embedding model: all parsed, without vectors.
    await asyncio.to_thread(run_worker, world, None, [Queue.INGEST, Queue.OCR])
    # As if old and scan had been chunked before their terms were written (migration 0016).
    world.db.execute(
        "UPDATE synapse.document_chunks SET search = NULL WHERE version_id IN (%s, %s)",
        (old["version_id"], scan["version_id"]),
    )
    database = Database(world.worker.database("test-reindex"), max_size=1)
    await database.open()
    try:
        without_model = await reindex(database, world.tenant_id, embed=False)
        assert without_model.terms_written == 2
        assert without_model.embedding_queued == 0
        searchable = world.db.execute(
            "SELECT search FROM synapse.document_chunks WHERE version_id = %s",
            (old["version_id"],),
        ).fetchone()
        assert searchable is not None
        assert searchable[0].startswith("eski")
        # OCR's second reading of the scan is written with the terms again.
        scanned = world.db.execute(
            "SELECT search FROM synapse.document_chunks WHERE version_id = %s",
            (scan["version_id"],),
        ).fetchone()
        assert scanned is not None
        assert "2026/36" in scanned[0].split()
        assert embedding_jobs(world, old["version_id"]) == 0
        with_model = await reindex(database, world.tenant_id, embed=True)
        assert with_model.terms_written == 0
        assert with_model.embedding_queued >= 2
    finally:
        await database.close()
    assert embedding_jobs(world, old["version_id"]) == 1
    assert embedding_jobs(world, plain["version_id"]) == 1
    await asyncio.to_thread(run_worker, world, None, [Queue.EMBED], StandInEmbedder())
    assert version_state(world, old["version_id"]) == ("ready", None)
    assert version_state(world, plain["version_id"]) == ("ready", None)


def test_the_context_skips_a_cover_page_read_by_ocr(world: World, editor: TestClient) -> None:
    # Page 1 has no text layer (a cover, read by OCR), page 2 has one.
    body = upload(
        editor, samples.pdf("", "Belediye meclisi toplandi ve karar verdi."), "kapakli.pdf"
    )
    run_worker(world, queues=ALL_QUEUES)
    context, _ = indexing(world, body["version_id"])
    assert context == "kapakli\nBelediye meclisi toplandi ve karar verdi."
    # The OCR text is still in the chunks, and a scan without any text layer keeps its own.
    texts = [c[2] for c in chunks_of(world, body["version_id"])]
    assert any("Karar 2026/35 okundu." in t for t in texts)
    scan = upload(editor, samples.pdf(""), "tarama-yalniz.pdf")
    run_worker(world, queues=ALL_QUEUES)
    assert indexing(world, scan["version_id"])[0] == "tarama yalniz\nKarar 2026/35 okundu."


def chunks_of(world: World, version_id: str) -> list[tuple[Any, ...]]:
    return [
        tuple(row)
        for row in world.db.execute(
            "SELECT ordinal, kind, text FROM synapse.document_chunks WHERE version_id = %s "
            "ORDER BY ordinal",
            (version_id,),
        ).fetchall()
    ]
