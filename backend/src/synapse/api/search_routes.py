"""Search: the chunks that answer a question, among the documents the user may read.

``POST`` so the question stays out of URLs and access logs. With ``rerank`` false the fused
first stage comes back at once (tens of milliseconds); with it true the reranker orders the
first 15 too, which takes seconds on a CPU (knowledge/search.py, docs/benchmarks/embeddings.md).
"""

from uuid import UUID

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from synapse.api.deps import ApiError, FullSession
from synapse.knowledge.public import MAX_QUERY, Found, Search

router = APIRouter(tags=["search"])


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_QUERY)
    limit: int = Field(default=10, ge=1, le=50)
    rerank: bool = True


class HitView(BaseModel):
    document_id: UUID
    title: str
    version: int
    page_start: int
    page_end: int
    kind: str
    heading_path: list[str]
    text: str
    lexical_rank: int | None
    dense_rank: int | None
    reranked: bool
    rerank_score: float | None


class SearchView(BaseModel):
    hits: list[HitView]
    reranked: bool
    # A stage left out because its model did not answer: embedding_unavailable,
    # reranking_unavailable.
    warnings: list[str]
    milliseconds: dict[str, float]


def _search(request: Request) -> Search:
    service: Search = request.app.state.search
    return service


@router.post("/api/search")
async def search(body: SearchRequest, session: FullSession, request: Request) -> SearchView:
    query = body.query.strip()
    if not query:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_CONTENT, "empty_query")
    service = _search(request)
    found: Found
    if body.rerank:
        found = await service.search(session.user_id, query, limit=body.limit)
    else:
        found = await service.candidates(session.user_id, query, limit=body.limit)
    return SearchView(
        hits=[
            HitView(
                document_id=hit.document_id,
                title=hit.title,
                version=hit.version,
                page_start=hit.page_start,
                page_end=hit.page_end,
                kind=hit.kind,
                heading_path=list(hit.heading_path),
                text=hit.text,
                lexical_rank=hit.lexical_rank,
                dense_rank=hit.dense_rank,
                reranked=hit.reranked,
                rerank_score=hit.rerank_score,
            )
            for hit in found.hits
        ],
        reranked=found.reranked,
        warnings=found.warnings,
        milliseconds=found.milliseconds,
    )
