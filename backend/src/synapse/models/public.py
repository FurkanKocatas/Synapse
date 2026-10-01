"""The models package's public interface. Other packages import from here only."""

from dataclasses import dataclass, field
from pathlib import Path

from synapse.kernel.config import Settings
from synapse.kernel.secrets import read_secret
from synapse.models.llama import LlamaChat, LlamaEmbedder, LlamaReranker, LlamaServer
from synapse.models.ports import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    ChatMessage,
    ChatModel,
    ChatReply,
    Embedder,
    ModelError,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
    Reranker,
)


@dataclass
class Models:
    """The model of each role this process may call; None where none is configured."""

    embedder: Embedder | None = None
    reranker: Reranker | None = None
    chat: ChatModel | None = None
    servers: list[LlamaServer] = field(default_factory=list, repr=False)

    async def close(self) -> None:
        for server in self.servers:
            await server.close()


def models_from(settings: Settings) -> Models:
    """The llama.cpp servers the settings name, with their keys read from their files."""
    servers: list[LlamaServer] = []

    def server(service: str, url: str, key_file: Path) -> LlamaServer:
        timeout = settings.model_timeout_seconds
        servers.append(LlamaServer(service, url, read_secret(key_file), timeout=timeout))
        return servers[-1]

    embed, rerank, chat = settings.embed_url, settings.rerank_url, settings.chat_url
    return Models(
        embedder=LlamaEmbedder(server("embedding", embed, settings.embed_key_file))
        if embed
        else None,
        reranker=LlamaReranker(server("reranking", rerank, settings.rerank_key_file))
        if rerank
        else None,
        chat=LlamaChat(server("chat", chat, settings.chat_key_file)) if chat else None,
        servers=servers,
    )


__all__ = [
    "EMBEDDING_DIMENSIONS",
    "EMBEDDING_MODEL",
    "ChatMessage",
    "ChatModel",
    "ChatReply",
    "Embedder",
    "ModelError",
    "ModelResponseError",
    "ModelTimeoutError",
    "ModelUnavailableError",
    "Models",
    "Reranker",
    "models_from",
]
