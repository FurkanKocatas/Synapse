"""Search: the chunks that answer a question, among the documents the user may read.

ADR 0010 (query rules) with the first stage ADR 0018 chose and docs/benchmarks/embeddings.md
measured:

1. **Candidates**, each query restricted to the newest searchable version (``parsed``,
   ``embedding`` or ``ready``) of every document ``accessible_documents`` gives the user, so a
   chunk the user may not read is never a candidate, whatever its score; and, when the user
   chose a scope (``scope.py``: folders, documents), to the documents in it:
   - lexical: BM25 of pg_textsearch over ``document_chunks.search``, the terms (``lexical_text``)
     of the document's context and the chunk (migration 0016), on the ``simple`` configuration,
     the question turned into terms the same way;
   - dense: bge-m3's vector of the question against the chunks' (HNSW, cosine), when an
     embedding model is configured.
   Both look for the question with the organisation's synonyms of what it names
   (``with_synonyms``, ADR 0010 query rule 1), and so does the reranker.
2. **Fusion** by reciprocal rank (k 60) of the two top-50 lists: ranks only. No score is ever
   compared with a threshold; fused scores have no absolute meaning (ADR 0010).
3. **Reranking** of the fusion's top 15 by the cross-encoder, the rest following in fused order.
   The fused order is available first (``candidates``), the reranked one when the reranker
   answers (``rerank``), so sources can be shown within the latency budget.

A model that does not answer leaves its stage out and says so in ``warnings``: search still
answers by words, and the user sees that it did.
"""

import re
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from uuid import UUID

import structlog
from psycopg import AsyncConnection

from synapse.kernel.database import Database
from synapse.knowledge.chunking import contextual_text
from synapse.knowledge.library import Overview, overview
from synapse.knowledge.scope import CHOSEN, EVERYTHING, IN_SCOPE, Scope
from synapse.knowledge.turkish import lower
from synapse.models.public import Embedder, ModelError, Reranker

log = structlog.get_logger(__name__)

CANDIDATES = 50
RERANK_TOP = 15
# Lexical terms (``lexical_text``): words cut to their first five letters, a stand-in for
# Turkish lemmas that ranked above PostgreSQL's Snowball stems on the golden set (Hit@10 0.963
# against 0.937 by words alone, docs/benchmarks/embeddings.md), and identifiers kept whole.
PREFIX = 5
MIN_IDENTIFIER = 4
_WORD = re.compile(r"\w+")
_IDENTIFIER = re.compile(r"[\w./-]*\d[\w./-]*")
RRF_K = 60
MAX_QUERY = 1000
# HNSW returns at most ef_search rows; iterative scans keep going when the permission filter
# drops rows, in exact distance order.
_HNSW = ("SET LOCAL hnsw.ef_search = 200", "SET LOCAL hnsw.iterative_scan = strict_order")

_SEARCHABLE = (
    CHOSEN  # noqa: S608
    + """, searchable AS MATERIALIZED (
        SELECT v.id FROM accessible_documents(%(user)s, 'read') a
        JOIN documents d ON d.id = a.document_id
        CROSS JOIN LATERAL (
            SELECT dv.id FROM document_versions dv
            WHERE dv.document_id = a.document_id AND dv.status IN ('parsed', 'embedding', 'ready')
            ORDER BY dv.version DESC LIMIT 1
        ) v
        WHERE """
    + IN_SCOPE
    + """
    )
"""
)
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
# The organisation's synonyms (synapse.organization validates them).
_SYNONYMS = "SELECT coalesce(settings->'synonyms', '[]'::jsonb) FROM tenant_settings"
_DETAILS = (
    "SELECT c.version_id, c.ordinal, v.document_id, d.title, v.version, c.kind, "
    "c.heading_path, c.text, c.page_start, c.page_end, coalesce(v.context, ''), "
    "array(SELECT DISTINCT u FROM document_pages p CROSS JOIN unnest(p.uncertain_identifiers) u "
    "WHERE p.version_id = c.version_id AND p.number BETWEEN c.page_start AND c.page_end "
    "ORDER BY u) "
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
    # The reranker's score (a logit): the one score with a meaning of its own, which refusal
    # before generation is calibrated on (ADR 0010, query rule 6). None when not reranked.
    rerank_score: float | None = None
    # Identifiers OCR read on the chunk's pages that its second reading did not confirm
    # (``uncertain_identifiers``): an answer that states one says so (chat/answering.py).
    uncertain: tuple[str, ...] = ()


@dataclass(frozen=True)
class Found:
    hits: list[Hit]
    reranked: bool
    warnings: list[str]
    milliseconds: dict[str, float]
    # What was searched for: the question with its synonyms (``with_synonyms``).
    searched: str = ""


def lexical_text(text: str) -> str:
    """The terms lexical search indexes and asks for, as one string for pg_textsearch's
    ``simple`` configuration: the text lower-cased the Turkish way, each word without a digit cut
    to its first five letters ("kararları" and "kararı": "karar"), and every identifier of four
    characters or more also whole ("2026/16", "e-81912396-105.04"), so a number is not matched
    only digit group by digit group."""
    folded = lower(text)
    words = _terms(folded)
    identifiers = [t.strip(".-/") for t in _IDENTIFIER.findall(folded)]
    whole = [t for t in identifiers if len(t) >= MIN_IDENTIFIER and not t.isdigit()]
    return " ".join([*words, *whole])


def _terms(text: str) -> list[str]:
    """The words of ``text`` as lexical search compares them: lower-cased the Turkish way, each
    word without a digit cut to its first five letters."""
    words = _WORD.findall(lower(text))
    return [w if any(ch.isdigit() for ch in w) else w[:PREFIX] for w in words]


def with_synonyms(query: str, groups: Sequence[Sequence[str]]) -> str:
    """The question and, after it, the other phrases of every group of synonyms it names:
    "KVKK" brings "Kişisel Verilerin Korunması Kanunu", and the other way round. Phrases are
    compared as lexical terms, so an inflected or capitalised form names one too ("KVKK'nın",
    "belediye kanununa")."""
    asked = _terms(query)
    added = [
        phrase
        for group in groups
        if any(_names(asked, phrase) for phrase in group)
        for phrase in group
        if not _names(asked, phrase)
    ]
    return "\n".join([query, "; ".join(added)]) if added else query


def _names(asked: list[str], phrase: str) -> bool:
    terms = _terms(phrase)
    width = len(terms)
    return width > 0 and any(asked[i : i + width] == terms for i in range(len(asked) - width + 1))


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

    async def candidates(
        self, user_id: UUID, query: str, *, limit: int = RERANK_TOP, scope: Scope = EVERYTHING
    ) -> Found:
        """The fused first stage: the ``limit`` best chunks by words and by meaning, within
        ``scope``, for the question with its synonyms."""
        warnings: list[str] = []
        timings: dict[str, float] = {}
        searched = with_synonyms(query, await self._synonyms())
        vector = await self._query_vector(searched, warnings, timings)
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            started = time.perf_counter()
            lexical = await self._lexical(connection, user_id, searched, scope)
            timings["lexical"] = _since(started)
            dense: list[Key] = []
            if vector is not None:
                started = time.perf_counter()
                dense = await self._dense(connection, user_id, vector, scope)
                timings["dense"] = _since(started)
            fused = fuse(lexical, dense)[:limit]
            hits = await _details(connection, fused, lexical, dense)
        return Found(
            hits, reranked=False, warnings=warnings, milliseconds=timings, searched=searched
        )

    async def rerank(self, query: str, found: Found, *, limit: int) -> Found:
        """The candidates' first 15 in the reranker's order, then the rest as they were; the
        reranker reads what the candidates were searched for, synonyms included."""
        if self._reranker is None or not found.hits:
            return replace(found, hits=found.hits[:limit])
        top, rest = found.hits[:RERANK_TOP], found.hits[RERANK_TOP:]
        started = time.perf_counter()
        try:
            scores = await self._reranker.rerank(
                found.searched or query,
                [contextual_text(h.context, h.heading_path, h.text) for h in top],
            )
        except ModelError as error:
            log.warning("search.rerank_unavailable", error=str(error))
            return replace(
                found, hits=found.hits[:limit], warnings=[*found.warnings, "reranking_unavailable"]
            )
        order = sorted(range(len(top)), key=lambda i: -scores[i])
        reranked = [replace(top[i], reranked=True, rerank_score=scores[i]) for i in order]
        return Found(
            [*reranked, *rest][:limit],
            reranked=True,
            warnings=found.warnings,
            milliseconds={**found.milliseconds, "rerank": _since(started)},
            searched=found.searched,
        )

    async def search(
        self, user_id: UUID, query: str, *, limit: int = 10, scope: Scope = EVERYTHING
    ) -> Found:
        found = await self.candidates(user_id, query, limit=max(limit, RERANK_TOP), scope=scope)
        return await self.rerank(query, found, limit=limit)

    async def _synonyms(self) -> list[list[str]]:
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            cursor = await connection.execute(_SYNONYMS)
            row = await cursor.fetchone()
        groups: list[list[str]] = row[0] if row else []
        return groups

    async def library(self, user_id: UUID, scope: Scope = EVERYTHING) -> Overview:
        """What the user's documents are (within ``scope``), for questions about the
        collection itself."""
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            return await overview(connection, user_id, scope=scope)

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

    async def _lexical(
        self, connection: AsyncConnection, user_id: UUID, query: str, scope: Scope
    ) -> list[Key]:
        cursor = await connection.execute(
            _LEXICAL,
            {
                "user": user_id,
                "limit": CANDIDATES,
                "query": lexical_text(query),
                **scope.parameters(),
            },
        )
        # Zero: none of the question's terms is in the chunk (see _LEXICAL).
        return [
            (version, ordinal) for version, ordinal, score in await cursor.fetchall() if score < 0
        ]

    async def _dense(
        self, connection: AsyncConnection, user_id: UUID, vector: str, scope: Scope
    ) -> list[Key]:
        for statement in _HNSW:
            await connection.execute(statement)
        cursor = await connection.execute(
            _DENSE,
            {"user": user_id, "limit": CANDIDATES, "vector": vector, **scope.parameters()},
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
        page_start, page_end, context, uncertain = row[8:]
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
                uncertain=tuple(uncertain),
            )
        )
    return hits


def _since(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
