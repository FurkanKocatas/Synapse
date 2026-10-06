"""Chat: questions answered from the user's documents (a corporate conversation), a plain
conversation with the chat model (a classic one), and the conversations they make.

``POST /api/chat`` answers as server-sent events (docs/design/answers.md), in this order:
``turn`` (where the turn is stored), ``rewritten`` (a follow-up as it was searched),
``sources`` (what the answer rests on: first in the fused order, ``ranked`` false, within a
second, then reranked), ``queued`` (the chat model is busy:
the position), ``generating``, ``delta`` (the answer as it is written), ``retrying`` (the text
so far is discarded: it stated a number no source holds), and ``answer`` last, the verified
answer. Closing the connection cancels the turn. A failure after the stream has started is an
``error`` event, since the status code has been sent.
"""

import json
from collections.abc import AsyncIterator
from contextlib import aclosing
from datetime import datetime
from typing import Literal
from uuid import UUID

import anyio
import structlog
from fastapi import APIRouter, Request, status
from fastapi.responses import StreamingResponse
from pydantic import AwareDatetime, BaseModel, Field

from synapse.api.deps import ApiError, FullSession, client_ip
from synapse.api.search_routes import ScopeModel
from synapse.chat.public import (
    Answer,
    Asker,
    ClassicChatDisabledError,
    ConversationNotFoundError,
    Conversations,
    Delta,
    Event,
    Generating,
    Queued,
    Retrying,
    Rewritten,
    Sources,
    Started,
)
from synapse.knowledge.public import MAX_QUERY

log = structlog.get_logger(__name__)

router = APIRouter(tags=["chat"])


type Mode = Literal["corporate", "classic"]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUERY)
    conversation_id: UUID | None = None
    # A new conversation's mode; an existing one keeps the mode it was started in.
    mode: Mode = "corporate"
    # The user's clock, with its offset, so the model knows the day and the hour.
    now: AwareDatetime | None = None
    # The folders and documents to search: kept by the conversation for the turns after. Left
    # out, the conversation's own scope (everything, for a new one).
    scope: ScopeModel | None = None


class SourceView(BaseModel):
    number: int
    document_id: UUID
    title: str
    version: int
    ordinal: int
    page_start: int
    page_end: int
    heading_path: list[str]
    # None when the user may no longer read the document.
    text: str | None


class TurnView(BaseModel):
    ordinal: int
    question: str
    status: str
    answer: str | None
    sources: list[SourceView]
    citations: list[int]
    feedback: str | None
    created_at: datetime
    # "documents", "conversation" or "general": what the answer rests on.
    kind: str
    # Identifiers of the answer OCR read uncertainly: to check against the document.
    uncertain: list[str]
    # Where the turn searched; both lists empty: everything the user could read.
    scope: ScopeModel


class ConversationSummaryView(BaseModel):
    id: UUID
    title: str
    updated_at: datetime
    mode: Mode


class ConversationDetailView(BaseModel):
    id: UUID
    title: str
    turns: list[TurnView]
    mode: Mode
    scope: ScopeModel


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class FeedbackRequest(BaseModel):
    kind: Literal["helpful", "wrong_source", "incomplete", "invented"] | None


def _conversations(request: Request) -> Conversations:
    service: Conversations = request.app.state.conversations
    return service


@router.post("/api/chat")
async def ask(body: AskRequest, session: FullSession, request: Request) -> StreamingResponse:
    question = body.question.strip()
    if not question:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_CONTENT, "empty_query")
    events = _conversations(request).ask(
        Asker(session.user_id, client_ip(request)),
        question,
        body.conversation_id,
        mode=body.mode,
        now=body.now,
        scope=body.scope.scope() if body.scope is not None else None,
    )
    try:
        first = await anext(events)  # the turn is stored, or the conversation is not the user's
    except ConversationNotFoundError as error:
        await events.aclose()
        raise ApiError(status.HTTP_404_NOT_FOUND, "not_found") from error
    except ClassicChatDisabledError as error:
        await events.aclose()
        raise ApiError(status.HTTP_403_FORBIDDEN, "classic_chat_disabled") from error

    async def stream() -> AsyncIterator[str]:
        try:
            yield _sse(first)
            async with aclosing(events) as rest:
                async for event in rest:
                    yield _sse(event)
        except Exception:
            log.exception("chat.stream_failed")
            yield _message("error", {"error": "internal_error"})
        finally:
            with anyio.CancelScope(shield=True):
                await events.aclose()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            # nginx passes each event on at once instead of buffering the answer.
            "X-Accel-Buffering": "no",
        },
    )


def _sse(event: Started | Event) -> str:
    data: dict[str, object]
    match event:
        case Started():
            name = "turn"
            data = {"conversation_id": str(event.conversation_id), "ordinal": event.ordinal}
        case Rewritten():
            name, data = "rewritten", {"question": event.question}
        case Sources():
            name = "sources"
            data = {
                "sources": [
                    SourceView(
                        number=n,
                        document_id=h.document_id,
                        title=h.title,
                        version=h.version,
                        ordinal=h.ordinal,
                        page_start=h.page_start,
                        page_end=h.page_end,
                        heading_path=list(h.heading_path),
                        text=h.text,
                    ).model_dump(mode="json")
                    for n, h in enumerate(event.hits, start=1)
                ],
                "warnings": event.warnings,
                "ranked": event.ranked,
            }
        case Queued():
            name, data = "queued", {"position": event.position}
        case Generating():
            name, data = "generating", {}
        case Delta():
            name, data = "delta", {"text": event.text}
        case Retrying():
            name, data = "retrying", {"unsupported": list(event.unsupported)}
        case Answer():
            name = "answer"
            data = {
                "status": event.status,
                "text": event.text,
                "citations": event.citations,
                "error": event.error,
                "stripped": len(event.stripped),
                "uncertain": list(event.uncertain),
                "kind": event.kind,
            }
    return _message(name, data)


def _message(name: str, data: dict[str, object]) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/api/conversations")
async def conversations(
    session: FullSession, request: Request, mode: Mode = "corporate"
) -> list[ConversationSummaryView]:
    found = await _conversations(request).list(session.user_id, mode)
    return [
        ConversationSummaryView(id=c.id, title=c.title, updated_at=c.updated_at, mode=c.mode)
        for c in found
    ]


@router.get("/api/conversations/{conversation_id}")
async def conversation(
    conversation_id: UUID, session: FullSession, request: Request
) -> ConversationDetailView:
    try:
        found = await _conversations(request).get(session.user_id, conversation_id)
    except ConversationNotFoundError as error:
        raise ApiError(status.HTTP_404_NOT_FOUND, "not_found") from error
    return ConversationDetailView(
        id=found.id,
        title=found.title,
        mode=found.mode,
        scope=ScopeModel.of(found.scope),
        turns=[
            TurnView(
                ordinal=t.ordinal,
                question=t.question,
                status=t.status,
                answer=t.answer,
                sources=[
                    SourceView(
                        number=n,
                        document_id=s.document_id,
                        title=s.title,
                        version=s.version,
                        ordinal=s.ordinal,
                        page_start=s.page_start,
                        page_end=s.page_end,
                        heading_path=list(s.heading_path),
                        text=s.text,
                    )
                    for n, s in enumerate(t.sources, start=1)
                ],
                citations=t.citations,
                feedback=t.feedback,
                created_at=t.created_at,
                kind=t.kind,
                uncertain=list(t.uncertain),
                scope=ScopeModel.of(t.scope),
            )
            for t in found.turns
        ],
    )


@router.patch("/api/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def rename(
    conversation_id: UUID, body: RenameRequest, session: FullSession, request: Request
) -> None:
    title = " ".join(body.title.split())
    if not title:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_CONTENT, "empty_title")
    try:
        await _conversations(request).rename(session.user_id, conversation_id, title)
    except ConversationNotFoundError as error:
        raise ApiError(status.HTTP_404_NOT_FOUND, "not_found") from error


@router.delete("/api/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(conversation_id: UUID, session: FullSession, request: Request) -> None:
    try:
        await _conversations(request).delete(
            Asker(session.user_id, client_ip(request)), conversation_id
        )
    except ConversationNotFoundError as error:
        raise ApiError(status.HTTP_404_NOT_FOUND, "not_found") from error


@router.put(
    "/api/conversations/{conversation_id}/turns/{ordinal}/feedback",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def feedback(
    conversation_id: UUID,
    ordinal: int,
    body: FeedbackRequest,
    session: FullSession,
    request: Request,
) -> None:
    try:
        await _conversations(request).feedback(session.user_id, conversation_id, ordinal, body.kind)
    except ConversationNotFoundError as error:
        raise ApiError(status.HTTP_404_NOT_FOUND, "not_found") from error
