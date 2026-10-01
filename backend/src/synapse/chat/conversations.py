"""Conversations: a user's questions, their answers and their sources, kept for that user.

Rules (docs/design/answers.md):

- A conversation belongs to the user who started it; another user gets "not found", the same as
  for a missing one, so identifiers cannot be probed.
- A turn is written ``pending`` before anything is searched, and finished with its answer, or
  ``cancelled`` when the user stops it or the connection closes. Finishing is shielded from
  that cancellation, so no turn is left pending by a closed tab.
- Every question is audited when its turn finishes (ADR 0008): the question, the documents
  retrieved and cited, the outcome, and the answer as a SHA-256 only.
- Sources are kept as references. Reading a conversation again fetches their text through
  ``accessible_documents``: a source the user may no longer read comes back without it.
"""

import hashlib
import json
from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import anyio
from psycopg import AsyncConnection

from synapse.audit import public as audit
from synapse.audit.public import AuditEvent
from synapse.chat.answering import Answer, Answerer, Event, Sources, Turn
from synapse.kernel.database import Database
from synapse.knowledge.public import Hit

MAX_TITLE = 200
TITLE_CHARS = 80
MAX_CONVERSATIONS = 200

type Feedback = Literal["helpful", "wrong_source", "incomplete", "invented"]


class ConversationNotFoundError(LookupError):
    """Missing, or another user's."""


@dataclass(frozen=True)
class Asker:
    user_id: UUID
    ip: str | None


@dataclass(frozen=True)
class Started:
    """The turn is stored: where it lives."""

    conversation_id: UUID
    ordinal: int


@dataclass(frozen=True)
class ConversationSummary:
    id: UUID
    title: str
    updated_at: datetime


@dataclass(frozen=True)
class StoredSource:
    document_id: UUID
    version_id: UUID
    version: int
    ordinal: int
    title: str
    page_start: int
    page_end: int
    # None when the user may no longer read the document, or it is gone.
    text: str | None
    heading_path: tuple[str, ...]


@dataclass(frozen=True)
class StoredTurn:
    ordinal: int
    question: str
    status: str
    answer: str | None
    sources: list[StoredSource]
    citations: list[int]
    feedback: str | None
    created_at: datetime


@dataclass(frozen=True)
class ConversationView:
    id: UUID
    title: str
    turns: list[StoredTurn]


_READABLE_CHUNKS = """
    SELECT c.version_id, c.ordinal, c.text, c.heading_path
    FROM unnest(%(versions)s::uuid[], %(ordinals)s::int[]) AS s(version_id, ordinal)
    JOIN document_chunks c ON c.version_id = s.version_id AND c.ordinal = s.ordinal
    JOIN document_versions v ON v.id = c.version_id
    WHERE v.document_id IN (SELECT document_id FROM accessible_documents(%(user)s, 'read'))
"""

_OWNED = "SELECT title FROM conversations WHERE id = %s AND user_id = %s"
_OWNED_FOR_UPDATE = _OWNED + " FOR UPDATE"


class Conversations:
    def __init__(
        self,
        database: Database,
        *,
        tenant_id: UUID,
        answerer: Answerer,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._db = database
        self._tenant_id = tenant_id
        self._answerer = answerer
        self._now = now

    async def ask(
        self, asker: Asker, question: str, conversation_id: UUID | None = None
    ) -> AsyncGenerator[Started | Event]:
        """Store the turn, answer it, finish it. Closing the iterator cancels the turn."""
        conversation_id, ordinal, history = await self._begin(asker, question, conversation_id)
        yield Started(conversation_id, ordinal)
        sources: list[Hit] = []
        finished = False
        try:
            answering = self._answerer.answer(asker.user_id, question, history)
            async with aclosing(answering) as events:
                async for event in events:
                    if isinstance(event, Sources):
                        sources = event.hits
                    if isinstance(event, Answer):
                        with anyio.CancelScope(shield=True):
                            await self._finish(
                                asker, conversation_id, ordinal, question, sources, event
                            )
                        finished = True
                    yield event
        except Exception:
            failed = Answer("failed", "", [], question, None, error="internal_error")
            with anyio.CancelScope(shield=True):
                await self._finish(asker, conversation_id, ordinal, question, sources, failed)
            finished = True
            raise
        finally:
            if not finished:
                with anyio.CancelScope(shield=True):
                    await self._finish(asker, conversation_id, ordinal, question, sources, None)

    async def _begin(
        self, asker: Asker, question: str, conversation_id: UUID | None
    ) -> tuple[UUID, int, list[Turn]]:
        now = self._now()
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            if conversation_id is None:
                cursor = await connection.execute(
                    "INSERT INTO conversations (tenant_id, user_id, title, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    (self._tenant_id, asker.user_id, _title(question), now, now),
                )
                conversation_id = _value(await cursor.fetchone())
                history: list[Turn] = []
            else:
                await self._owned(connection, asker.user_id, conversation_id, lock=True)
                history = await _history(connection, conversation_id)
                await connection.execute(
                    "UPDATE conversations SET updated_at = %s WHERE id = %s", (now, conversation_id)
                )
            cursor = await connection.execute(
                "INSERT INTO conversation_turns (tenant_id, conversation_id, ordinal, question, "
                "created_at) SELECT %s, %s, coalesce(max(ordinal), 0) + 1, %s, %s "
                "FROM conversation_turns WHERE conversation_id = %s RETURNING ordinal",
                (self._tenant_id, conversation_id, question, now, conversation_id),
            )
            ordinal: int = _value(await cursor.fetchone())
        return conversation_id, ordinal, history

    async def _finish(
        self,
        asker: Asker,
        conversation_id: UUID,
        ordinal: int,
        question: str,
        sources: list[Hit],
        answer: Answer | None,
    ) -> None:
        status = answer.status if answer else "cancelled"
        text = answer.text if answer and answer.status == "answered" else None
        citations = answer.citations if answer else []
        details: dict[str, Any] = {}
        if answer is not None:
            details = {
                "best_score": answer.best_score,
                "retried": answer.retried,
                "stripped": list(answer.stripped),
                "error": answer.error,
                "seconds": answer.seconds,
                "checked": asdict(answer.checked) if answer.checked else None,
            }
        references = [
            {
                "document_id": str(h.document_id),
                "version_id": str(h.version_id),
                "version": h.version,
                "ordinal": h.ordinal,
                "title": h.title,
                "page_start": h.page_start,
                "page_end": h.page_end,
            }
            for h in sources
        ]
        now = self._now()
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            await connection.execute(
                "UPDATE conversation_turns SET status = %s, query = %s, answer = %s, "
                "sources = %s, citations = %s, details = %s, finished_at = %s "
                "WHERE conversation_id = %s AND ordinal = %s",
                (
                    status,
                    answer.question if answer else None,
                    text,
                    json.dumps(references),
                    citations,
                    json.dumps(details),
                    now,
                    conversation_id,
                    ordinal,
                ),
            )
            cited = [str(sources[n - 1].document_id) for n in citations if 1 <= n <= len(sources)]
            await audit.record(
                connection,
                self._tenant_id,
                AuditEvent(
                    "chat.question",
                    "success" if status in {"answered", "not_found", "insufficient"} else "failure",
                    actor_user_id=asker.user_id,
                    actor_ip=asker.ip,
                    target_type="conversation",
                    target_id=str(conversation_id),
                    details={
                        "turn": ordinal,
                        "question": question,
                        "status": status,
                        "retrieved": list(dict.fromkeys(str(h.document_id) for h in sources)),
                        "cited": list(dict.fromkeys(cited)),
                        "answer_sha256": hashlib.sha256(text.encode()).hexdigest() if text else "",
                    },
                ),
                now,
            )

    async def list(self, user_id: UUID) -> list[ConversationSummary]:
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            cursor = await connection.execute(
                "SELECT id, title, updated_at FROM conversations WHERE user_id = %s "
                "ORDER BY updated_at DESC LIMIT %s",
                (user_id, MAX_CONVERSATIONS),
            )
            return [ConversationSummary(*row) for row in await cursor.fetchall()]

    async def get(self, user_id: UUID, conversation_id: UUID) -> ConversationView:
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            title = await self._owned(connection, user_id, conversation_id)
            cursor = await connection.execute(
                "SELECT ordinal, question, status, answer, sources, citations, feedback, "
                "created_at FROM conversation_turns WHERE conversation_id = %s ORDER BY ordinal",
                (conversation_id,),
            )
            rows = await cursor.fetchall()
            references = [s for row in rows for s in row[4]]
            cursor = await connection.execute(
                _READABLE_CHUNKS,
                {
                    "versions": [r["version_id"] for r in references],
                    "ordinals": [r["ordinal"] for r in references],
                    "user": user_id,
                },
            )
            readable = {(row[0], row[1]): (row[2], row[3]) for row in await cursor.fetchall()}
        turns = []
        for ordinal, question, status, answer, sources, citations, feedback, created in rows:
            stored = []
            for s in sources:
                text, headings = readable.get((UUID(s["version_id"]), s["ordinal"]), (None, []))
                stored.append(
                    StoredSource(
                        document_id=UUID(s["document_id"]),
                        version_id=UUID(s["version_id"]),
                        version=s["version"],
                        ordinal=s["ordinal"],
                        title=s["title"] if text is not None else "",
                        page_start=s["page_start"],
                        page_end=s["page_end"],
                        text=text,
                        heading_path=tuple(headings),
                    )
                )
            turns.append(
                StoredTurn(
                    ordinal, question, status, answer, stored, list(citations), feedback, created
                )
            )
        return ConversationView(conversation_id, title, turns)

    async def rename(self, user_id: UUID, conversation_id: UUID, title: str) -> None:
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            await self._owned(connection, user_id, conversation_id, lock=True)
            await connection.execute(
                "UPDATE conversations SET title = %s WHERE id = %s",
                (title[:MAX_TITLE], conversation_id),
            )

    async def delete(self, asker: Asker, conversation_id: UUID) -> None:
        now = self._now()
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            await self._owned(connection, asker.user_id, conversation_id, lock=True)
            await connection.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
            await audit.record(
                connection,
                self._tenant_id,
                AuditEvent(
                    "chat.conversation.delete",
                    "success",
                    actor_user_id=asker.user_id,
                    actor_ip=asker.ip,
                    target_type="conversation",
                    target_id=str(conversation_id),
                ),
                now,
            )

    async def feedback(
        self, user_id: UUID, conversation_id: UUID, ordinal: int, kind: Feedback | None
    ) -> None:
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            await self._owned(connection, user_id, conversation_id)
            cursor = await connection.execute(
                "UPDATE conversation_turns SET feedback = %s "
                "WHERE conversation_id = %s AND ordinal = %s AND status <> 'pending'",
                (kind, conversation_id, ordinal),
            )
            if cursor.rowcount == 0:
                raise ConversationNotFoundError

    async def _owned(
        self,
        connection: AsyncConnection,
        user_id: UUID,
        conversation_id: UUID,
        *,
        lock: bool = False,
    ) -> str:
        """The conversation's title; ``ConversationNotFoundError`` unless the user owns it."""
        cursor = await connection.execute(
            _OWNED_FOR_UPDATE if lock else _OWNED, (conversation_id, user_id)
        )
        row = await cursor.fetchone()
        if row is None:
            raise ConversationNotFoundError
        title: str = row[0]
        return title


async def _history(connection: AsyncConnection, conversation_id: UUID) -> list[Turn]:
    cursor = await connection.execute(
        "SELECT question, answer FROM conversation_turns "
        "WHERE conversation_id = %s AND status = 'answered' ORDER BY ordinal",
        (conversation_id,),
    )
    return [Turn(question, answer) for question, answer in await cursor.fetchall()]


def _title(question: str) -> str:
    words = " ".join(question.split())
    return words if len(words) <= TITLE_CHARS else words[: TITLE_CHARS - 1].rstrip() + "…"


def _value[T](row: tuple[T, ...] | None) -> T:
    if row is None:  # pragma: no cover  (INSERT ... RETURNING always returns a row)
        raise RuntimeError("no row returned")
    return row[0]
