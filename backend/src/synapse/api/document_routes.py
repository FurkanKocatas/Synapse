"""Knowledge base endpoints: documents in collections, their versions and files.

Uploads are the raw file as the request body, with the original name in the ``filename`` query
parameter. The body is written to disk as it arrives, with the size limit enforced on the way,
and only after the permission check, so a user who may not upload cannot fill the disk.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from synapse.api.deps import ApiError, FullSession, client_ip
from synapse.knowledge.public import (
    BlobStore,
    DocumentService,
    DuplicateError,
    Incoming,
    NotFoundError,
    Receiver,
    TooLargeError,
    UnsupportedFileError,
    Uploaded,
    Uploader,
)

router = APIRouter(tags=["documents"])

Filename = Annotated[str, Query(min_length=1, max_length=1024)]
READ_BLOCK = 1 << 20


def _documents(request: Request) -> DocumentService:
    service: DocumentService = request.app.state.documents
    return service


def _blobs(request: Request) -> BlobStore:
    store: BlobStore = request.app.state.blobs
    return store


class UploadedView(BaseModel):
    id: UUID
    version_id: UUID
    version: int
    media_type: str


class DocumentView(BaseModel):
    id: UUID
    collection_id: UUID
    title: str
    latest_version: int
    status: str
    media_type: str
    size_bytes: int
    updated_at: datetime


class VersionView(BaseModel):
    id: UUID
    version: int
    filename: str
    media_type: str
    size_bytes: int
    status: str
    failure: str | None
    created_at: datetime


async def _receive(request: Request) -> Incoming:
    limit = request.app.state.upload_max_bytes
    receiver = Receiver(_blobs(request).incoming_dir(), limit_bytes=limit)
    try:
        async for block in request.stream():
            await asyncio.to_thread(receiver.write, block)
    except TooLargeError as error:
        raise ApiError(status.HTTP_413_CONTENT_TOO_LARGE, "file_too_large") from error
    except BaseException:
        receiver.discard()
        raise
    incoming = receiver.finish()
    if incoming.size_bytes == 0:
        incoming.path.unlink(missing_ok=True)
        raise ApiError(status.HTTP_400_BAD_REQUEST, "empty_file")
    return incoming


def _uploaded(result: Uploaded) -> UploadedView:
    return UploadedView(
        id=result.document_id,
        version_id=result.version_id,
        version=result.version,
        media_type=result.media_type.value,
    )


@router.post("/api/collections/{collection_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload(
    collection_id: UUID,
    filename: Filename,
    session: FullSession,
    request: Request,
    title: Annotated[str | None, Query(max_length=500)] = None,
) -> UploadedView:
    documents = _documents(request)
    if not await documents.may_upload(session.user_id, collection_id):
        raise ApiError(status.HTTP_404_NOT_FOUND, "not_found")
    incoming = await _receive(request)
    try:
        uploaded = await documents.upload(
            Uploader(session.user_id, client_ip(request)), collection_id, incoming, filename, title
        )
    except BaseException as error:
        incoming.path.unlink(missing_ok=True)
        raise _translate(error) from error
    return _uploaded(uploaded)


@router.post("/api/documents/{document_id}/versions", status_code=status.HTTP_201_CREATED)
async def add_version(
    document_id: UUID, filename: Filename, session: FullSession, request: Request
) -> UploadedView:
    documents = _documents(request)
    if not await documents.may_add_version(session.user_id, document_id):
        raise ApiError(status.HTTP_404_NOT_FOUND, "not_found")
    incoming = await _receive(request)
    try:
        uploaded = await documents.add_version(
            Uploader(session.user_id, client_ip(request)), document_id, incoming, filename
        )
    except BaseException as error:
        incoming.path.unlink(missing_ok=True)
        raise _translate(error) from error
    return _uploaded(uploaded)


def _translate(error: BaseException) -> BaseException:
    if isinstance(error, UnsupportedFileError):
        return ApiError(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, error.reason)
    if isinstance(error, DuplicateError):
        return ApiError(status.HTTP_409_CONFLICT, "duplicate_document")
    if isinstance(error, NotFoundError):
        return ApiError(status.HTTP_404_NOT_FOUND, "not_found")
    return error


@router.get("/api/collections/{collection_id}/documents")
async def list_documents(
    collection_id: UUID, session: FullSession, request: Request
) -> list[DocumentView]:
    found = await _documents(request).list_documents(session.user_id, collection_id)
    return [DocumentView(**vars(document)) for document in found]


@router.get("/api/documents/{document_id}/versions")
async def versions(document_id: UUID, session: FullSession, request: Request) -> list[VersionView]:
    try:
        found = await _documents(request).versions(session.user_id, document_id)
    except NotFoundError as error:
        raise ApiError(status.HTTP_404_NOT_FOUND, "not_found") from error
    return [VersionView(**vars(version)) for version in found]


@router.get("/api/documents/{document_id}/versions/{version}/file")
async def download(
    document_id: UUID, version: int, session: FullSession, request: Request
) -> StreamingResponse:
    try:
        stored = await _documents(request).stored_file(session.user_id, document_id, version)
    except NotFoundError as error:
        raise ApiError(status.HTTP_404_NOT_FOUND, "not_found") from error
    blobs = _blobs(request)
    tenant_id: UUID = request.app.state.tenant_id

    async def body() -> AsyncIterator[bytes]:
        handle = await asyncio.to_thread(blobs.open, tenant_id, stored.sha256)
        try:
            while block := await asyncio.to_thread(handle.read, READ_BLOCK):
                yield block
        finally:
            handle.close()

    return StreamingResponse(
        body(),
        media_type=stored.media_type,
        headers={
            # Always a download, never rendered in the application's origin.
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(stored.filename)}",
            "Content-Length": str(stored.size_bytes),
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "Cache-Control": "private, no-store",
        },
    )


@router.delete("/api/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(document_id: UUID, session: FullSession, request: Request) -> None:
    try:
        await _documents(request).delete(Uploader(session.user_id, client_ip(request)), document_id)
    except NotFoundError as error:
        raise ApiError(status.HTTP_404_NOT_FOUND, "not_found") from error
