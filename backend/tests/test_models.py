"""The llama.cpp adapters against a stand-in server (the real ones run in the stack smoke test).

The stand-in tokenizes one token per word, adds <s> (0) and </s> (2) when asked, and records
every request, so the tests can check what the adapters send as well as what they return.
"""

import json
import math
from pathlib import Path
from typing import Any

import httpx2
import pytest
from pydantic import ValidationError

from synapse.kernel.config import Settings
from synapse.models.llama import LlamaChat, LlamaEmbedder, LlamaReranker, LlamaServer, collapse
from synapse.models.public import (
    EMBEDDING_DIMENSIONS,
    ChatDelta,
    ChatMessage,
    ChatReply,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
    models_from,
)

KEY = "test-key"


class FakeLlama:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.words: dict[str, int] = {}
        self.reply: dict[str, Any] = {}
        # Server-sent events a streamed chat call gets, each a JSON object or a raw line.
        self.events: list[dict[str, Any] | str] = []
        self.status = 200

    def id(self, word: str) -> int:
        return self.words.setdefault(word, 10 + len(self.words))

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        assert request.headers["Authorization"] == f"Bearer {KEY}"
        body = json.loads(request.content)
        self.requests.append((request.url.path, body))
        if self.status != 200:
            return httpx2.Response(self.status, json={"error": {"message": "broken"}})
        if body.get("stream"):
            lines = [e if isinstance(e, str) else f"data: {json.dumps(e)}" for e in self.events]
            content = "".join(f"{line}\n\n" for line in [*lines, "data: [DONE]"])
            return httpx2.Response(
                200, content=content.encode(), headers={"Content-Type": "text/event-stream"}
            )
        routes = {
            "/tokenize": self._tokenize,
            "/detokenize": self._detokenize,
            "/v1/embeddings": self._embeddings,
            "/v1/rerank": self._rerank,
            "/v1/chat/completions": self._chat,
        }
        return httpx2.Response(200, json=routes[request.url.path](body))

    def _chat(self, body: dict[str, Any]) -> dict[str, Any]:
        return self.reply

    def _tokenize(self, body: dict[str, Any]) -> dict[str, Any]:
        tokens = [self.id(w) for w in body["content"].split(" ") if w]
        return {"tokens": [0, *tokens, 2] if body["add_special"] else tokens}

    def _detokenize(self, body: dict[str, Any]) -> dict[str, Any]:
        names = {v: k for k, v in self.words.items()}
        return {"content": " ".join(names[t] for t in body["tokens"])}

    def _embeddings(self, body: dict[str, Any]) -> dict[str, Any]:
        vectors = self.reply.get("vectors") or [
            # Each text's vector points its own way: its first word's id against 1.
            [float(ids[1]), 1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 2)
            for ids in body["input"]
        ]
        # The server's order is not promised; the index is.
        return {"data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)][::-1]}

    def _rerank(self, body: dict[str, Any]) -> dict[str, Any]:
        return {
            "results": self.reply.get("results")
            or [
                {"index": i, "relevance_score": float(len(d))}
                for i, d in enumerate(body["documents"])
            ]
        }

    def server(self, service: str = "test") -> LlamaServer:
        return LlamaServer(
            service,
            "http://model:8080",
            KEY,
            timeout=5,
            transport=httpx2.MockTransport(self.handle),
        )

    def paths(self) -> list[str]:
        return [path for path, _ in self.requests]


async def test_embedding_sends_cut_token_ids_and_returns_unit_vectors() -> None:
    fake = FakeLlama()
    embedder = LlamaEmbedder(fake.server(), max_tokens=5)
    vectors = await embedder.embed(["bir  iki\n\nüç", "a b c d e f g"])
    tokenized = [body for path, body in fake.requests if path == "/tokenize"]
    assert [b["content"] for b in tokenized] == ["bir iki üç", "a b c d e f g"]
    assert all(b["add_special"] for b in tokenized)
    (sent,) = [body["input"] for path, body in fake.requests if path == "/v1/embeddings"]
    # Cut inside the start and end tokens, as the model's own tokenizer cuts.
    assert sent[0] == [0, fake.id("bir"), fake.id("iki"), fake.id("üç"), 2]
    assert sent[1] == [0, fake.id("a"), fake.id("b"), fake.id("c"), 2]
    # In the texts' order although the server answered in reverse, each of length one.
    assert [len(v) for v in vectors] == [EMBEDDING_DIMENSIONS] * 2
    assert [round(v[0] / v[1]) for v in vectors] == [fake.id("bir"), fake.id("a")]
    assert all(math.isclose(sum(x * x for x in v), 1.0) for v in vectors)
    assert await embedder.embed([]) == []


@pytest.mark.parametrize(
    "vectors",
    [
        [[1.0] * (EMBEDDING_DIMENSIONS - 1)],  # wrong dimension
        [[0.0] * EMBEDDING_DIMENSIONS],  # no direction
        [[1.0] * EMBEDDING_DIMENSIONS, [1.0] * EMBEDDING_DIMENSIONS],  # one too many
    ],
)
async def test_embedding_rejects_wrong_vectors(vectors: list[list[float]]) -> None:
    fake = FakeLlama()
    fake.reply = {"vectors": vectors}
    with pytest.raises(ModelResponseError, match="embedding"):
        await LlamaEmbedder(fake.server("embedding")).embed(["metin"])


async def test_rerank_cuts_long_passages_to_fit_with_the_question() -> None:
    fake = FakeLlama()
    reranker = LlamaReranker(fake.server(), max_tokens=10)
    # The question takes 2 tokens and the pair 4 special ones: 4 tokens are left per passage.
    scores = await reranker.rerank("ne  zaman", ["kısa", "bir iki üç dört beş altı"])
    (sent,) = [body for path, body in fake.requests if path == "/v1/rerank"]
    assert sent["query"] == "ne zaman"
    assert sent["documents"] == ["kısa", "bir iki üç dört"]
    assert sent["top_n"] == 2
    # A passage no longer than the room in characters is never tokenized.
    assert {"content": "kısa", "add_special": False} not in [b for _, b in fake.requests]
    assert scores == [4.0, 15.0]
    assert await reranker.rerank("soru", []) == []


async def test_rerank_rejects_unscored_passages_and_too_long_questions() -> None:
    fake = FakeLlama()
    fake.reply = {"results": [{"index": 0, "relevance_score": 1.0}]}
    with pytest.raises(ModelResponseError, match="unscored"):
        await LlamaReranker(fake.server()).rerank("soru", ["bir", "iki"])
    with pytest.raises(ModelResponseError, match="too long"):
        await LlamaReranker(FakeLlama().server(), max_tokens=6).rerank("a b c", ["metin"])


async def test_chat_asks_for_deterministic_json_and_reads_timings() -> None:
    fake = FakeLlama()
    fake.reply = {
        "choices": [{"message": {"content": '{"answer": "12 Mart 2025"}'}}],
        "timings": {
            "prompt_n": 2800,
            "prompt_ms": 16600.0,
            "predicted_n": 40,
            "predicted_ms": 1900,
        },
    }
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    reply = await LlamaChat(fake.server()).complete(
        [ChatMessage("system", "Kaynakları kullan."), ChatMessage("user", "Ne zaman?")],
        schema=schema,
        max_tokens=400,
    )
    ((_, body),) = fake.requests
    assert body["temperature"] == 0
    assert body["max_tokens"] == 400
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["response_format"]["json_schema"]["schema"] == schema
    assert body["messages"][1] == {"role": "user", "content": "Ne zaman?"}
    assert reply.content == '{"answer": "12 Mart 2025"}'
    assert (reply.prompt_tokens, reply.prompt_seconds) == (2800, 16.6)
    assert (reply.generated_tokens, reply.generated_seconds) == (40, 1.9)

    fake.reply = {"choices": [{"message": {"content": "metin"}}]}
    plain = await LlamaChat(fake.server()).complete([ChatMessage("user", "Merhaba")])
    assert "response_format" not in fake.requests[-1][1]
    assert plain.prompt_tokens is None
    fake.reply = {"choices": []}
    with pytest.raises(ModelResponseError, match="no message"):
        await LlamaChat(fake.server()).complete([ChatMessage("user", "Merhaba")])


def delta(text: str) -> dict[str, Any]:
    return {"choices": [{"index": 0, "delta": {"content": text}}]}


async def test_chat_streams_deltas_then_the_whole_reply_with_timings() -> None:
    fake = FakeLlama()
    fake.events = [
        {"choices": [{"index": 0, "delta": {"role": "assistant"}}]},
        delta('{"answer": "12 '),
        ": a comment line, ignored",
        delta('Mart"}'),
        delta(""),
        {"choices": [], "timings": {"prompt_n": 2800, "prompt_ms": 16600.0, "predicted_n": 9}},
    ]
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    parts = [
        part
        async for part in LlamaChat(fake.server()).stream(
            [ChatMessage("user", "Ne zaman?")], schema=schema, max_tokens=300
        )
    ]
    ((_, body),) = fake.requests
    assert body["stream"] is True
    assert body["max_tokens"] == 300
    assert body["response_format"]["json_schema"]["schema"] == schema
    assert parts[:2] == [ChatDelta('{"answer": "12 '), ChatDelta('Mart"}')]
    (reply,) = parts[2:]
    assert isinstance(reply, ChatReply)
    assert reply.content == '{"answer": "12 Mart"}'
    assert (reply.prompt_tokens, reply.prompt_seconds, reply.generated_tokens) == (2800, 16.6, 9)


@pytest.mark.parametrize(
    ("events", "message"),
    [
        (["data: {not json"], "streamed no JSON"),
        (["data: [1]"], "streamed list"),
        ([{"error": {"message": "context full"}}], "streamed an error"),
        ([{"choices": [{"index": 0}]}], "streamed no delta"),
    ],
)
async def test_bad_streams_are_typed(events: list[dict[str, Any] | str], message: str) -> None:
    fake = FakeLlama()
    fake.events = events
    with pytest.raises(ModelResponseError, match=message):
        async for _ in LlamaChat(fake.server("chat")).stream([ChatMessage("user", "Merhaba")]):
            pass


@pytest.mark.parametrize(
    ("status", "error"), [(503, ModelUnavailableError), (400, ModelResponseError)]
)
async def test_stream_errors_are_typed(status: int, error: type[Exception]) -> None:
    fake = FakeLlama()
    fake.status = status
    with pytest.raises(error, match=f"chat: /v1/chat/completions answered {status}: broken"):
        async for _ in LlamaChat(fake.server("chat")).stream([ChatMessage("user", "Merhaba")]):
            pass


@pytest.mark.parametrize(
    ("raised", "error"),
    [
        (httpx2.ConnectError("refused"), ModelUnavailableError),
        (httpx2.ReadTimeout("slow"), ModelTimeoutError),
    ],
)
async def test_stream_transport_failures_are_typed(
    raised: Exception, error: type[Exception]
) -> None:
    def fail(request: httpx2.Request) -> httpx2.Response:
        raise raised

    server = LlamaServer(
        "chat", "http://model:8080", KEY, timeout=5, transport=httpx2.MockTransport(fail)
    )
    with pytest.raises(error, match="chat: /v1/chat/completions"):
        async for _ in LlamaChat(server).stream([ChatMessage("user", "Merhaba")]):
            pass


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (500, ModelUnavailableError),
        (503, ModelUnavailableError),
        (400, ModelResponseError),
        (401, ModelResponseError),
    ],
)
async def test_server_errors_are_typed(status: int, error: type[Exception]) -> None:
    fake = FakeLlama()
    fake.status = status
    with pytest.raises(error, match=f"embedding: /tokenize answered {status}: broken"):
        await LlamaEmbedder(fake.server("embedding")).embed(["metin"])


@pytest.mark.parametrize(
    ("raised", "error"),
    [
        (httpx2.ConnectError("refused"), ModelUnavailableError),
        (httpx2.ReadTimeout("slow"), ModelTimeoutError),
    ],
)
async def test_transport_failures_are_typed(raised: Exception, error: type[Exception]) -> None:
    def fail(request: httpx2.Request) -> httpx2.Response:
        raise raised

    server = LlamaServer(
        "chat", "http://model:8080", KEY, timeout=5, transport=httpx2.MockTransport(fail)
    )
    with pytest.raises(error, match="chat: /v1/chat/completions"):
        await LlamaChat(server).complete([ChatMessage("user", "Merhaba")])


@pytest.mark.parametrize("content", [b"not json", b"[1, 2]", b'{"tokens": "x"}'])
async def test_malformed_answers_are_typed(content: bytes) -> None:
    server = LlamaServer(
        "embedding",
        "http://model:8080",
        KEY,
        timeout=5,
        transport=httpx2.MockTransport(lambda request: httpx2.Response(200, content=content)),
    )
    with pytest.raises(ModelResponseError, match="embedding: /tokenize"):
        await LlamaEmbedder(server).embed(["metin"])


def test_collapse_joins_every_kind_of_whitespace() -> None:
    assert collapse(" a\t\tb\n\n c d\r\n") == "a b c d"


def test_models_come_from_the_settings_with_their_keys(tmp_path: Path) -> None:
    for role in ("embed", "rerank", "chat"):
        (tmp_path / role).write_text(f"{role}-key\n", encoding="utf-8")
    settings = Settings(
        embed_url="http://llm-embed:8080",
        embed_key_file=tmp_path / "embed",
        rerank_url="",
        chat_url="https://chat.internal:8443",
        chat_key_file=tmp_path / "chat",
    )
    models = models_from(settings)
    assert isinstance(models.embedder, LlamaEmbedder)
    assert models.reranker is None
    assert isinstance(models.chat, LlamaChat)
    assert [s.service for s in models.servers] == ["embedding", "chat"]
    assert models_from(Settings()).servers == []


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "http://llm:8080/v1", "ftp://llm:21", "llm:8080"]
)
def test_model_urls_are_plain_http_addresses(url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(embed_url=url)


async def test_closing_models_closes_their_clients(tmp_path: Path) -> None:
    (tmp_path / "key").write_text("k", encoding="utf-8")
    models = models_from(
        Settings(embed_url="http://llm-embed:8080", embed_key_file=tmp_path / "key")
    )
    await models.close()
    with pytest.raises(RuntimeError):
        await models.servers[0].post("/tokenize", {})


@pytest.mark.parametrize(("status", "healthy"), [(200, True), (503, False)])
async def test_a_server_is_healthy_once_its_model_is_loaded(status: int, *, healthy: bool) -> None:
    def answer(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/health"
        return httpx2.Response(status, json={"status": "ok" if status == 200 else "loading"})

    server = LlamaServer(
        "chat", "http://model:8080", KEY, timeout=5, transport=httpx2.MockTransport(answer)
    )
    assert await server.healthy() is healthy


async def test_a_server_that_does_not_answer_is_not_healthy() -> None:
    def fail(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    server = LlamaServer(
        "chat", "http://model:8080", KEY, timeout=5, transport=httpx2.MockTransport(fail)
    )
    assert await server.healthy() is False
