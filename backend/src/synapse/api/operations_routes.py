"""The operations page (ADR 0014): ``GET /api/admin/operations``, its figures, and
``POST /api/admin/operations/retry``, processing again what stopped on an error."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Request

from synapse.api.deps import client_ip, require
from synapse.identity.public import CurrentSession
from synapse.operations.public import Operations, Overview, Retried

router = APIRouter(prefix="/api/admin", tags=["admin"])

ViewOperations = Annotated[CurrentSession, require("operations.view")]
ManageOperations = Annotated[CurrentSession, require("operations.manage")]


@router.get("/operations")
async def operations(_session: ViewOperations, request: Request) -> Overview:
    service: Operations = request.app.state.operations
    return await service.overview()


@router.post("/operations/retry")
async def retry(session: ManageOperations, request: Request) -> Retried:
    service: Operations = request.app.state.operations
    return await service.retry(session.user_id, client_ip(request), datetime.now(UTC))
