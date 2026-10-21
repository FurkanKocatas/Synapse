"""How many of the fusion's first chunks the reranker reads."""

from collections.abc import Sequence
from typing import Any
from uuid import uuid4

from synapse.knowledge.search import RERANK_TOP, Found, Hit, Search


class Counting:
    """A reranker that prefers the later passages and counts what it read."""

    def __init__(self) -> None:
        self.read: list[int] = []

    async def rerank(self, query: str, passages: Sequence[str]) -> list[float]:
        self.read.append(len(passages))
        return [float(i) for i in range(len(passages))]


def found(n: int) -> Found:
    document = uuid4()
    hits = [
        Hit(
            document_id=document,
            title="Belge",
            version_id=document,
            version=1,
            ordinal=i,
            kind="text",
            heading_path=(),
            text=f"metin {i}",
            page_start=1,
            page_end=1,
            context="",
            lexical_rank=i + 1,
            dense_rank=None,
        )
        for i in range(n)
    ]
    return Found(hits, reranked=False, warnings=[], milliseconds={})


async def test_the_reranker_reads_as_many_candidates_as_set() -> None:
    database: Any = None
    for top in (RERANK_TOP, 30):
        reranker = Counting()
        search = Search(database, tenant_id=uuid4(), reranker=reranker, rerank_top=top)
        result = await search.rerank("soru", found(40), limit=40)
        assert reranker.read == [top]
        assert [h.reranked for h in result.hits] == [True] * top + [False] * (40 - top)
        # The reranker's favourite of those it read comes first: the last of them.
        assert result.hits[0].ordinal == top - 1
