"""The three model ports (ADR 0009): the only way the application calls a model.

Adapters implement them (``llama.py``); no other code talks to a model server. A call that
fails raises a ``ModelError`` subclass, which callers show or record; it is never swallowed.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

# ADR 0018: bge-m3's dense vectors. The name is stored with every vector, so vectors of another
# model are never compared with these; the schema's column has this many dimensions.
EMBEDDING_MODEL = "bge-m3"
EMBEDDING_DIMENSIONS = 1024


class ModelError(Exception):
    """A model call failed. ``service`` names the role: embedding, reranking or chat."""

    def __init__(self, service: str, message: str) -> None:
        super().__init__(f"{service}: {message}")
        self.service = service


class ModelUnavailableError(ModelError):
    """The server could not be reached or answered with a server error."""


class ModelTimeoutError(ModelError):
    """The server did not answer in time."""


class ModelResponseError(ModelError):
    """The server answered, but not with what the call needs (a client error or bad data)."""


class Embedder(Protocol):
    model: str
    dimensions: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Unit-length vectors, one per text, in order."""
        ...


class Reranker(Protocol):
    async def rerank(self, query: str, passages: Sequence[str]) -> list[float]:
        """One relevance score per passage, in order; higher is more relevant."""
        ...


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ChatReply:
    content: str
    # Timings as the server reports them, for the latency budget (ADR 0009); None if absent.
    prompt_tokens: int | None = None
    prompt_seconds: float | None = None
    generated_tokens: int | None = None
    generated_seconds: float | None = None


class ChatModel(Protocol):
    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        schema: Mapping[str, Any] | None = None,
        max_tokens: int = 1024,
    ) -> ChatReply:
        """The model's reply; with ``schema``, JSON the server constrains to it."""
        ...
