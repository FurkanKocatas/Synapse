"""``GET /api/admin/operations``: the operations page's figures (ADR 0014)."""

from typing import Annotated

from fastapi import APIRouter, Request

from synapse.api.deps import require
from synapse.identity.public import CurrentSession
from synapse.operations.public import Operations, Overview

router = APIRouter(prefix="/api/admin", tags=["admin"])

ViewOperations = Annotated[CurrentSession, require("operations.view")]


@router.get("/operations")
async def operations(_session: ViewOperations, request: Request) -> Overview:
    service: Operations = request.app.state.operations
    return await service.overview()
