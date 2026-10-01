"""Search: the chunks that answer a question, among the documents the user may read.

ADR 0010 (query rules) with the first stage ADR 0018 chose and docs/benchmarks/embeddings.md
measured:

1. **Candidates**, each query restricted to the newest searchable version (``parsed``,
   ``embedding`` or ``ready``) of every document ``accessible_documents`` gives the user, so a
   chunk the user may not read is never a candidate, whatever its score:
   - lexical: BM25 of pg_textsearch over ``document_chunks.search`` (the document's context and
     the chunk, lower-cased the Turkish way; migration 0015) on PostgreSQL's ``turkish``
     configuration, the question lower-cased the same way;
   - dense: bge-m3's vector of the question against the chunks' (HNSW, cosine), when an
     embedding model is configured.
2. **Fusion** by reciprocal rank (k 60) of the two top-50 lists: ranks only. No score is ever
   compared with a threshold; fused scores have no absolute meaning (ADR 0010).
3. **Reranking** of the fusion's top 15 by the cross-encoder, the rest following in fused order.
   The fused order is available first (``candidates``), the reranked one when the reranker
   answers (``rerank``), so sources can be shown within the latency budget.

A model that does not answer leaves its stage out and says so in ``warnings``: search still
answers by words, and the user sees that it did.
"""

import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from uuid import UUID

import structlog
from psycopg import AsyncConnection

from synapse.kernel.database import Database
from synapse.knowledge.chunking import contextual_text
from synapse.knowledge.turkish import lower
from synapse.models.public import Embedder, ModelError, Reranker

log = structlog.get_logger(__name__)

CANDIDATES = 50
RERANK_TOP = 15
RRF_K = 60
MAX_QUERY = 1000
# HNSW returns at most ef_search rows; iterative scans keep going when the permission filter
# drops rows, in exact distance order.
_HNSW = ("SET LOCAL hnsw.ef_search = 200", "SET LOCAL hnsw.iterative_scan = strict_order")

_SEARCHABLE = """
    WITH searchable AS MATERIALIZED (
        SELECT v.id FROM accessible_documents(%(user)s, 'read') a
        CROSS JOIN LATERAL (
            SELECT dv.id FROM document_versions dv
            WHERE dv.document_id = a.document_id AND dv.status IN ('parsed', 'embedding', 'ready')
            ORDER BY dv.version DESC LIMIT 1
        ) v
    )
"""
# pg_textsearch scores a match below zero (the best first in ascending order) and a chunk that
# holds none of the question's terms zero. Those are not found by words, so they are left out;
# a filter on the permission makes PostgreSQL score every row, and it would list them all.
# The statements are built from constant fragments; every value is a parameter.
_LEXICAL = (
    _SEARCHABLE + "SELECT c.version_id, c.ordinal, "  # noqa: S608
    "c.search <@> to_bm25query(%(query)s, 'document_chunks_search') AS score "
    "FROM document_chunks c WHERE c.version_id IN (SELECT id FROM searchable) "
    "AND c.search IS NOT NULL ORDER BY score LIMIT %(limit)s"
)
_DENSE = (
    _SEARCHABLE + "SELECT c.version_id, c.ordinal FROM document_chunks c "  # noqa: S608
    "WHERE c.version_id IN (SELECT id FROM searchable) AND c.embedding IS NOT NULL "
    "ORDER BY c.embedding <=> %(vector)s::halfvec LIMIT %(limit)s"
)
_DETAILS = (
    "SELECT c.version_id, c.ordinal, v.document_id, d.title, v.version, c.kind, "
    "c.heading_path, c.text, c.page_start, c.page_end, coalesce(v.context, '') "
    "FROM document_chunks c JOIN document_versions v ON v.id = c.version_id "
    "JOIN documents d ON d.id = v.document_id "
    "WHERE (c.version_id, c.ordinal) IN (SELECT * FROM unnest(%s::uuid[], %s::int[]))"
)

type Key = tuple[UUID, int]  # a chunk: its version and its ordinal


@dataclass(frozen=True)
class Hit:
    document_id: UUID
    title: str
    version_id: UUID
    version: int
    ordinal: int
    kind: str
    heading_path: tuple[str, ...]
    text: str
    page_start: int
    page_end: int
    context: str = field(repr=False)
    # 1-based ranks in each first-stage list, None when the chunk was not in it.
    lexical_rank: int | None
    dense_rank: int | None
    reranked: bool = False


@dataclass(frozen=True)
class Found:
    hits: list[Hit]
    reranked: bool
    warnings: list[str]
    milliseconds: dict[str, float]


def fuse(*rankings: Sequence[Key], k: int = RRF_K) -> list[Key]:
    """Reciprocal rank fusion: ranks only. Ties keep the order of first appearance."""
    scores: dict[Key, float] = defaultdict(float)
    first: dict[Key, int] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking):
            scores[key] += 1 / (k + rank + 1)
            first.setdefault(key, len(first))
    return sorted(scores, key=lambda key: (-scores[key], first[key]))


class Search:
    def __init__(
        self,
        database: Database,
        *,
        tenant_id: UUID,
        embedder: Embedder | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self._db = database
        self._tenant_id = tenant_id
        self._embedder = embedder
        self._reranker = reranker

    async def candidates(self, user_id: UUID, query: str, *, limit: int = RERANK_TOP) -> Found:
        """The fused first stage: the ``limit`` best chunks by words and by meaning."""
        warnings: list[str] = []
        timings: dict[str, float] = {}
        vector = await self._query_vector(query, warnings, timings)
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            started = time.perf_counter()
            lexical = await self._lexical(connection, user_id, query)
            timings["lexical"] = _since(started)
            dense: list[Key] = []
            if vector is not None:
                started = time.perf_counter()
                dense = await self._dense(connection, user_id, vector)
                timings["dense"] = _since(started)
            fused = fuse(lexical, dense)[:limit]
            hits = await _details(connection, fused, lexical, dense)
        return Found(hits, reranked=False, warnings=warnings, milliseconds=timings)

    async def rerank(self, query: str, found: Found, *, limit: int) -> Found:
        """The candidates' first 15 in the reranker's order, then the rest as they were."""
        if self._reranker is None or not found.hits:
            return replace(found, hits=found.hits[:limit])
        top, rest = found.hits[:RERANK_TOP], found.hits[RERANK_TOP:]
        started = time.perf_counter()
        try:
            scores = await self._reranker.rerank(
                query, [contextual_text(h.context, h.heading_path, h.text) for h in top]
            )
        except ModelError as error:
            log.warning("search.rerank_unavailable", error=str(error))
            return replace(
                found, hits=found.hits[:limit], warnings=[*found.warnings, "reranking_unavailable"]
            )
        order = sorted(range(len(top)), key=lambda i: -scores[i])
        reranked = [replace(top[i], reranked=True) for i in order]
        return Found(
            [*reranked, *rest][:limit],
            reranked=True,
            warnings=found.warnings,
            milliseconds={**found.milliseconds, "rerank": _since(started)},
        )

    async def search(self, user_id: UUID, query: str, *, limit: int = 10) -> Found:
        found = await self.candidates(user_id, query, limit=max(limit, RERANK_TOP))
        return await self.rerank(query, found, limit=limit)

    async def _query_vector(
        self, query: str, warnings: list[str], timings: dict[str, float]
    ) -> str | None:
        """The question's vector as pgvector reads it; None without a (reachable) model."""
        if self._embedder is None:
            return None
        started = time.perf_counter()
        try:
            (values,) = await self._embedder.embed([query])
        except ModelError as error:
            log.warning("search.embedding_unavailable", error=str(error))
            warnings.append("embedding_unavailable")
            return None
        timings["embed"] = _since(started)
        return "[" + ",".join(f"{v:.6g}" for v in values) + "]"

    async def _lexical(self, connection: AsyncConnection, user_id: UUID, query: str) -> list[Key]:
        cursor = await connection.execute(
            _LEXICAL, {"user": user_id, "limit": CANDIDATES, "query": lower(query)}
        )
        # Zero: none of the question's terms is in the chunk (see _LEXICAL).
        return [
            (version, ordinal) for version, ordinal, score in await cursor.fetchall() if score < 0
        ]

    async def _dense(self, connection: AsyncConnection, user_id: UUID, vector: str) -> list[Key]:
        for statement in _HNSW:
            await connection.execute(statement)
        cursor = await connection.execute(
            _DENSE, {"user": user_id, "limit": CANDIDATES, "vector": vector}
        )
        return [(version, ordinal) for version, ordinal in await cursor.fetchall()]


async def _details(
    connection: AsyncConnection, keys: list[Key], lexical: list[Key], dense: list[Key]
) -> list[Hit]:
    if not keys:
        return []
    cursor = await connection.execute(
        _DETAILS, ([version for version, _ in keys], [ordinal for _, ordinal in keys])
    )
    rows = {(row[0], row[1]): row for row in await cursor.fetchall()}
    lexical_rank = {key: rank for rank, key in enumerate(lexical, start=1)}
    dense_rank = {key: rank for rank, key in enumerate(dense, start=1)}
    hits = []
    for key in keys:
        row = rows.get(key)
        if row is None:  # pragma: no cover  (same transaction: the chunk cannot have gone)
            continue
        version_id, ordinal, document_id, title, version, kind, headings, text = row[:8]
        page_start, page_end, context = row[8:]
        hits.append(
            Hit(
                document_id=document_id,
                title=title,
                version_id=version_id,
                version=version,
                ordinal=ordinal,
                kind=kind,
                heading_path=tuple(headings),
                text=text,
                page_start=page_start,
                page_end=page_end,
                context=context,
                lexical_rank=lexical_rank.get(key),
                dense_rank=dense_rank.get(key),
            )
        )
    return hits


def _since(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
