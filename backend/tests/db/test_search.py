"""Search over ingested documents: words, meaning, fusion, reranking and who may see what.

Documents go through the real upload, worker and queue (as in test_ingest_pipeline.py) with a
stand-in embedding model; the real models run in the full-stack smoke test. Every test signs
in an editor of its own, who sees only the collections they created, so the tests do not see
each other's documents, and the permission filter is exercised on every search.
"""

import asyncio
import math
import uuid
import zlib
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from synapse import accounts_cli
from synapse.api.app import create_app
from synapse.api.deps import CLIENT_HEADER, CSRF_HEADER
from synapse.jobs.queue import Queue
from synapse.kernel.database import Database
from synapse.knowledge.public import Search
from synapse.knowledge.search import RERANK_TOP, fuse
from synapse.knowledge.turkish import lower
from synapse.models.public import ModelUnavailableError
from tests import knowledge_samples as samples
from tests.db.conftest import TestDatabase
from tests.db.test_ingest_pipeline import PASSWORD, World, make_world, run_worker, upload

QUEUES = (Queue.INGEST, Queue.OCR, Queue.EMBED)
# Words the stand-in model takes for one meaning, as a real one would.
SAME_MEANING = {"ziraat": "tarım", "zirai": "tarım", "tarımsal": "tarım"}


@dataclass
class BagOfWords:
    """A stand-in embedding model: one dimension per word (its first five letters), words of the
    same meaning on the same dimension."""

    fail: bool = False
    model: str = "bge-m3"
    dimensions: int = 1024

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if self.fail:
            raise ModelUnavailableError("embedding", "/tokenize: connection refused")
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for written in lower(text).split():
            word = SAME_MEANING.get(written.strip(".,:;"), written.strip(".,:;"))[:5]
            vector[zlib.crc32(word.encode()) % self.dimensions] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


@dataclass
class Prefers:
    """A stand-in reranker that puts passages containing ``word`` first."""

    word: str
    fail: bool = False
    seen: list[int] = field(default_factory=list)

    async def rerank(self, query: str, passages: Sequence[str]) -> list[float]:
        if self.fail:
            raise ModelUnavailableError("reranking", "/v1/rerank answered 503: loading")
        self.seen.append(len(passages))
        return [1.0 if self.word in lower(p) else 0.0 for p in passages]


@dataclass(frozen=True)
class Editor:
    client: TestClient
    user_id: uuid.UUID


@pytest.fixture(scope="module")
def world(test_database: TestDatabase, tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    yield from make_world(test_database, tmp_path_factory)


@pytest.fixture
def editor(world: World) -> Iterator[Editor]:
    email = f"searcher-{uuid.uuid4().hex[:8]}@example.org"
    user_id = accounts_cli.create_user(
        world.api,
        email=email,
        display_name="Searcher",
        role="editor",
        locale="tr",
        password=PASSWORD,
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
async def database(world: World) -> AsyncIterator[Database]:
    db = Database(world.api.database("test-search"), max_size=2)
    await db.open()
    yield db
    await db.close()


def ingest(world: World, editor: Editor, *texts: str) -> list[dict[str, str]]:
    uploaded = [
        upload(editor.client, samples.paragraphs(text), f"belge-{n}.docx")
        for n, text in enumerate(texts)
    ]
    run_worker(world, queues=QUEUES, embedder=BagOfWords())
    return uploaded


def search(
    world: World,
    database: Database,
    **models: object,
) -> Search:
    return Search(database, tenant_id=world.tenant_id, **models)  # type: ignore[arg-type]


COUNCIL = "Belediye meclisinin 2026/35 sayılı kararları oybirliğiyle kabul edildi."
BUDGET = "Bütçe raporu yıllık harcamaları ve gelirleri gösterir."
FARMING = "Ziraat arazileri her yıl düzenli olarak sulanır."


async def test_words_find_chunks_by_their_stems_and_identifiers(
    world: World,
    editor: Editor,
    database: Database,
) -> None:
    council, budget, _, igdir = await asyncio.to_thread(
        ingest, world, editor, COUNCIL, BUDGET, FARMING, "Iğdır il sınırları içinde kalır."
    )
    service = search(world, database)
    # "kararı" and "kararları" share their stem; the version's context is searched too.
    found = await service.candidates(editor.user_id, "Meclis kararı")
    assert [h.document_id for h in found.hits] == [uuid.UUID(council["id"])]
    assert found.hits[0].lexical_rank == 1
    assert found.hits[0].dense_rank is None  # no embedding model here
    assert (await service.candidates(editor.user_id, "2026/35")).hits[0].text == COUNCIL
    by_capitals = await service.candidates(editor.user_id, "GELİRLERİ")
    assert [h.document_id for h in by_capitals.hits] == [uuid.UUID(budget["id"])]
    # Turkish capitals: "IĞDIR" is "ığdır"; PostgreSQL's own lower would make it "iğdir".
    dotless = await service.candidates(editor.user_id, "IĞDIR")
    assert [h.document_id for h in dotless.hits] == [uuid.UUID(igdir["id"])]
    assert found.warnings == []


async def test_meaning_finds_what_words_miss(
    world: World,
    editor: Editor,
    database: Database,
) -> None:
    _, _, farming = await asyncio.to_thread(ingest, world, editor, COUNCIL, BUDGET, FARMING)
    words_only = await search(world, database).candidates(editor.user_id, "tarım")
    assert words_only.hits == []
    found = await search(world, database, embedder=BagOfWords()).candidates(editor.user_id, "tarım")
    first = found.hits[0]
    assert first.document_id == uuid.UUID(farming["id"])
    assert (first.lexical_rank, first.dense_rank) == (None, 1)
    assert set(found.milliseconds) == {"embed", "lexical", "dense"}


async def test_fused_results_are_never_cut_by_a_score(
    world: World,
    editor: Editor,
    database: Database,
) -> None:
    await asyncio.to_thread(ingest, world, editor, COUNCIL, BUDGET, FARMING)
    # Nothing shares a word with the question, so every fused score is low; all still come back.
    found = await search(world, database, embedder=BagOfWords()).candidates(
        editor.user_id, "xylofon"
    )
    assert len(found.hits) == 3
    assert all(h.lexical_rank is None for h in found.hits)


async def test_a_user_sees_only_what_they_may_read(
    world: World,
    editor: Editor,
    database: Database,
) -> None:
    await asyncio.to_thread(ingest, world, editor, COUNCIL)
    email = f"other-{uuid.uuid4().hex[:8]}@example.org"
    other = await asyncio.to_thread(
        accounts_cli.create_user,
        world.api,
        email=email,
        display_name="Other",
        role="editor",
        locale="tr",
        password=PASSWORD,
    )
    service = search(world, database, embedder=BagOfWords())
    # The best match by words and by meaning, and still not a candidate for someone else.
    assert (await service.candidates(other, COUNCIL)).hits == []
    assert len((await service.candidates(editor.user_id, COUNCIL)).hits) == 1


async def test_deleted_documents_and_replaced_versions_drop_out(
    world: World,
    editor: Editor,
    database: Database,
) -> None:
    council, budget = await asyncio.to_thread(ingest, world, editor, COUNCIL, BUDGET)
    service = search(world, database)
    assert editor.client.delete(f"/api/documents/{budget['id']}").status_code == 204
    assert (await service.candidates(editor.user_id, "harcamaları")).hits == []
    replaced = editor.client.post(
        f"/api/documents/{council['id']}/versions",
        params={"filename": "belge-0.docx"},
        content=samples.paragraphs("Meclis 2026/36 sayılı kararı erteledi."),
    )
    assert replaced.status_code == 201, replaced.json()
    await asyncio.to_thread(run_worker, world, None, QUEUES, BagOfWords())
    assert (await service.candidates(editor.user_id, "oybirliğiyle")).hits == []
    newest = (await service.candidates(editor.user_id, "2026/36")).hits
    assert [(h.document_id, h.version) for h in newest] == [(uuid.UUID(council["id"]), 2)]


async def test_the_reranker_orders_the_first_fifteen(
    world: World,
    editor: Editor,
    database: Database,
) -> None:
    # By words: 14 chunks with all three terms, then the one the reranker prefers with two
    # (15th: the last it reads), then three with one.
    texts = [f"Karar {n}: meclis bu konuyu görüştü." for n in range(14)]
    texts += ["Karar 14: meclis öncelikle görüştü."]
    texts += [f"Karar {n}: meclis toplandı." for n in range(15, 18)]
    await asyncio.to_thread(ingest, world, editor, *texts)
    fused = await search(world, database).candidates(
        editor.user_id, "meclis konuyu görüştü", limit=18
    )
    assert "öncelikle" in fused.hits[RERANK_TOP - 1].text
    reranker = Prefers("öncelik")
    service = search(world, database, reranker=reranker)
    found = await service.search(editor.user_id, "meclis konuyu görüştü", limit=18)
    assert reranker.seen == [RERANK_TOP]
    assert found.reranked
    assert "öncelikle" in found.hits[0].text
    assert [h.reranked for h in found.hits] == [True] * RERANK_TOP + [False] * 3
    assert "rerank" in found.milliseconds

    failing = search(world, database, reranker=Prefers("öncelik", fail=True))
    fallback = await failing.search(editor.user_id, "meclis konuyu görüştü", limit=5)
    assert not fallback.reranked
    assert fallback.warnings == ["reranking_unavailable"]
    assert len(fallback.hits) == 5


async def test_an_unreachable_embedding_model_leaves_the_words(
    world: World,
    editor: Editor,
    database: Database,
) -> None:
    council, *_ = await asyncio.to_thread(ingest, world, editor, COUNCIL)
    found = await search(world, database, embedder=BagOfWords(fail=True)).candidates(
        editor.user_id, "meclis kararları"
    )
    assert found.warnings == ["embedding_unavailable"]
    assert [h.document_id for h in found.hits] == [uuid.UUID(council["id"])]


def test_the_search_endpoint(world: World, editor: Editor) -> None:
    council, *_ = ingest(world, editor, COUNCIL, BUDGET)
    response = editor.client.post("/api/search", json={"query": "meclis kararları"})
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["hits"][0]["document_id"] == council["id"]
    assert body["hits"][0]["title"] == "belge-0"
    assert (body["hits"][0]["page_start"], body["hits"][0]["page_end"]) == (1, 1)
    # No model servers in the test settings: words only, nothing to rerank, nothing failed.
    assert (body["reranked"], body["warnings"]) == (False, [])
    quick = editor.client.post("/api/search", json={"query": "bütçe", "rerank": False, "limit": 1})
    assert len(quick.json()["hits"]) == 1
    for bad in ({"query": "   "}, {"query": ""}, {"query": "x", "limit": 0}, {"query": "x" * 1001}):
        assert editor.client.post("/api/search", json=bad).status_code == 422, bad


def test_fusion_ranks_by_rank_only() -> None:
    a, b, c, d = ((uuid.uuid4(), n) for n in range(4))
    # c is second in both lists and beats a, first in one only; ties keep first appearance.
    assert fuse([a, c, d], [b, c]) == [c, a, b, d]
    assert fuse([], []) == []
    assert fuse([a, b]) == [a, b]
