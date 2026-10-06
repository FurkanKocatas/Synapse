"""The model ports on llama.cpp's ``llama-server`` (ADR 0009, ADR 0018).

One server per role, on the internal network, each with its own API key. Texts are cut to the
model's length with the server's own tokenizer (``/tokenize``), so no input is ever too long for
it; runs of whitespace are collapsed first, as the models' own tokenizers do (llama.cpp's does
not always, and a table chunk once came out 93 tokens longer there).

- Embedding: the texts' token ids, truncated, to ``/v1/embeddings``; vectors made unit length.
- Reranking: each passage, truncated so that question and passage fit together, as text to
  ``/v1/rerank`` (it takes no token ids).
- Chat: ``/v1/chat/completions`` at temperature 0, optionally under a JSON schema the server
  enforces, whole or streamed as server-sent events. Thinking is off on the server
  (``--reasoning-budget 0``). Closing a stream closes its connection, and llama-server stops
  generating for a client that has gone.

Measured in docs/benchmarks/embeddings.md and answers.md; eval/retrieval/llama_encoder.py is the
benchmark's version of the same calls.
"""

import asyncio
import json
import math
from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import aclosing
from typing import Any

import httpx2

from synapse.models.ports import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    ChatDelta,
    ChatMessage,
    ChatReply,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
)

# bge-m3 and its reranker read 512 tokens; the servers are started with at least that per slot.
MAX_TOKENS = 512
# XLM-R pairs a question with a passage as <s> question </s></s> passage </s>.
PAIR_SPECIAL_TOKENS = 4
SERVER_ERROR = 500
# A health check waits no longer than this: the operations page asks every server at once.
HEALTH_TIMEOUT = 3.0
OK = 200


def collapse(text: str) -> str:
    return " ".join(text.split())


class LlamaServer:
    """One llama-server: its address, its key and the error mapping every call shares."""

    def __init__(
        self,
        service: str,
        url: str,
        api_key: str,
        *,
        timeout: float,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self.service = service
        self._client = httpx2.AsyncClient(
            base_url=url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
            # The servers are fixed internal addresses; an answer pointing elsewhere is an error.
            follow_redirects=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def healthy(self) -> bool:
        """Whether the server answers ``/health`` with its model loaded (503 while loading)."""
        try:
            response = await self._client.get("/health", timeout=HEALTH_TIMEOUT)
        except httpx2.TransportError:
            return False
        return response.status_code == OK

    async def post(self, path: str, body: Mapping[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(path, json=body)
        except httpx2.TimeoutException as error:
            raise ModelTimeoutError(self.service, f"{path} timed out") from error
        except httpx2.TransportError as error:
            raise ModelUnavailableError(self.service, f"{path}: {error}") from error
        if response.status_code >= SERVER_ERROR:
            raise ModelUnavailableError(
                self.service, f"{path} answered {response.status_code}: {_message(response)}"
            )
        if response.is_error:
            raise ModelResponseError(
                self.service, f"{path} answered {response.status_code}: {_message(response)}"
            )
        try:
            data = response.json()
        except ValueError as error:
            raise ModelResponseError(self.service, f"{path} did not answer JSON") from error
        if not isinstance(data, dict):
            raise ModelResponseError(self.service, f"{path} answered {type(data).__name__}")
        return data

    async def events(self, path: str, body: Mapping[str, Any]) -> AsyncGenerator[dict[str, Any]]:
        """The server-sent events of a streamed call, each decoded, until ``[DONE]``."""
        try:
            async with self._client.stream("POST", path, json=body) as response:
                if response.is_error:
                    await response.aread()
                    kind = (
                        ModelUnavailableError
                        if response.status_code >= SERVER_ERROR
                        else ModelResponseError
                    )
                    raise kind(
                        self.service,
                        f"{path} answered {response.status_code}: {_message(response)}",
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        return
                    yield self._event(path, data)
        except httpx2.TimeoutException as error:
            raise ModelTimeoutError(self.service, f"{path} timed out") from error
        except httpx2.TransportError as error:
            raise ModelUnavailableError(self.service, f"{path}: {error}") from error

    def _event(self, path: str, data: str) -> dict[str, Any]:
        try:
            event = json.loads(data)
        except ValueError as error:
            raise ModelResponseError(self.service, f"{path} streamed no JSON") from error
        if not isinstance(event, dict):
            raise ModelResponseError(self.service, f"{path} streamed {type(event).__name__}")
        if "error" in event:
            raise ModelResponseError(self.service, f"{path} streamed an error: {event['error']}")
        return event

    async def tokens(self, text: str, *, special: bool) -> list[int]:
        data = await self.post("/tokenize", {"content": text, "add_special": special})
        tokens = data.get("tokens")
        if not isinstance(tokens, list) or not all(isinstance(t, int) for t in tokens):
            raise ModelResponseError(self.service, "/tokenize answered no token list")
        return tokens

    async def text(self, tokens: Sequence[int]) -> str:
        data = await self.post("/detokenize", {"tokens": list(tokens)})
        content = data.get("content")
        if not isinstance(content, str):
            raise ModelResponseError(self.service, "/detokenize answered no text")
        return content


def _message(response: httpx2.Response) -> str:
    try:
        error = response.json().get("error", {})
        return str(error.get("message", "")) if isinstance(error, dict) else str(error)
    except ValueError, AttributeError:
        return response.text[:200]


class LlamaEmbedder:
    model = EMBEDDING_MODEL
    dimensions = EMBEDDING_DIMENSIONS

    def __init__(self, server: LlamaServer, *, max_tokens: int = MAX_TOKENS) -> None:
        self._server = server
        self._max_tokens = max_tokens

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        ids = await asyncio.gather(*(self._ids(text) for text in texts))
        data = await self._server.post("/v1/embeddings", {"input": ids})
        items = data.get("data")
        if not isinstance(items, list) or len(items) != len(texts):
            raise ModelResponseError(
                self._server.service, "/v1/embeddings: wrong number of vectors"
            )
        vectors = []
        for item in sorted(items, key=lambda item: item.get("index", -1)):
            vector = item.get("embedding")
            if not isinstance(vector, list) or len(vector) != self.dimensions:
                raise ModelResponseError(
                    self._server.service, f"/v1/embeddings: not {self.dimensions} dimensions"
                )
            vectors.append(_unit(vector, self._server.service))
        return vectors

    async def _ids(self, text: str) -> list[int]:
        """The text's tokens with the model's start and end tokens, cut inside them."""
        tokens = await self._server.tokens(collapse(text), special=True)
        if len(tokens) > self._max_tokens:
            tokens = [*tokens[: self._max_tokens - 1], tokens[-1]]
        return tokens


def _unit(vector: list[Any], service: str) -> list[float]:
    values = [float(v) for v in vector]
    norm = math.sqrt(sum(v * v for v in values))
    if not math.isfinite(norm) or norm == 0:
        raise ModelResponseError(service, "/v1/embeddings: a vector without a direction")
    return [v / norm for v in values]


class LlamaReranker:
    def __init__(self, server: LlamaServer, *, max_tokens: int = MAX_TOKENS) -> None:
        self._server = server
        self._max_tokens = max_tokens

    async def rerank(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        query = collapse(query)
        room = self._max_tokens - PAIR_SPECIAL_TOKENS
        room -= len(await self._server.tokens(query, special=False))
        if room <= 0:
            raise ModelResponseError(self._server.service, "the question alone is too long")
        documents = await asyncio.gather(*(self._fit(collapse(p), room) for p in passages))
        body = {"query": query, "documents": documents, "top_n": len(documents)}
        results = (await self._server.post("/v1/rerank", body)).get("results")
        if not isinstance(results, list):
            raise ModelResponseError(self._server.service, "/v1/rerank answered no results")
        scores: list[float | None] = [None] * len(documents)
        for item in results:
            index, score = item.get("index"), item.get("relevance_score")
            if (
                isinstance(index, int)
                and 0 <= index < len(scores)
                and isinstance(score, int | float)
            ):
                scores[index] = float(score)
        if any(score is None for score in scores):
            raise ModelResponseError(self._server.service, "/v1/rerank left passages unscored")
        return [score for score in scores if score is not None]

    async def _fit(self, passage: str, room: int) -> str:
        # A token is at least one character, so a passage this short always fits.
        if len(passage) <= room:
            return passage
        tokens = await self._server.tokens(passage, special=False)
        return passage if len(tokens) <= room else await self._server.text(tokens[:room])


class LlamaChat:
    def __init__(self, server: LlamaServer) -> None:
        self._server = server

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        schema: Mapping[str, Any] | None = None,
        max_tokens: int = 1024,
    ) -> ChatReply:
        data = await self._server.post(
            "/v1/chat/completions", _chat_body(messages, schema, max_tokens)
        )
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ModelResponseError(self._server.service, "chat answered no message") from error
        if not isinstance(content, str):
            raise ModelResponseError(self._server.service, "chat answered no text")
        return _reply(content, data.get("timings"))

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        schema: Mapping[str, Any] | None = None,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[ChatDelta | ChatReply]:
        body = {**_chat_body(messages, schema, max_tokens), "stream": True}
        parts: list[str] = []
        timings: object = None
        async with aclosing(self._server.events("/v1/chat/completions", body)) as events:
            async for event in events:
                # The last event carries the timings, and may carry no choice at all.
                timings = event.get("timings") or timings
                choices = event.get("choices")
                if not choices:
                    continue
                try:
                    text = choices[0]["delta"].get("content")
                except (KeyError, IndexError, TypeError, AttributeError) as error:
                    raise ModelResponseError(
                        self._server.service, "chat streamed no delta"
                    ) from error
                if isinstance(text, str) and text:
                    parts.append(text)
                    yield ChatDelta(text)
        yield _reply("".join(parts), timings)


def _chat_body(
    messages: Sequence[ChatMessage], schema: Mapping[str, Any] | None, max_tokens: int
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "temperature": 0,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if schema is not None:
        body["response_format"] = {"type": "json_schema", "json_schema": {"schema": schema}}
    return body


def _reply(content: str, timings: object) -> ChatReply:
    found = timings if isinstance(timings, dict) else {}
    return ChatReply(
        content=content,
        prompt_tokens=_number(found.get("prompt_n"), int),
        prompt_seconds=_seconds(found.get("prompt_ms")),
        generated_tokens=_number(found.get("predicted_n"), int),
        generated_seconds=_seconds(found.get("predicted_ms")),
    )


def _number[T: (int, float)](value: object, kind: type[T]) -> T | None:
    return kind(value) if isinstance(value, int | float) else None


def _seconds(milliseconds: object) -> float | None:
    value = _number(milliseconds, float)
    return None if value is None else value / 1000
