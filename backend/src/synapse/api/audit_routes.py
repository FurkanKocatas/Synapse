"""Audit endpoints under ``/api/audit``, for the auditor role (ADR 0008)."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from synapse.api.deps import require
from synapse.audit import public as audit
from synapse.kernel.database import Database

router = APIRouter(prefix="/api/audit", tags=["audit"])


class ChainStatus(BaseModel):
    ok: bool
    events_checked: int
    problem: str | None


@router.get("/status", dependencies=[require("audit.read")])
async def chain_status(request: Request) -> ChainStatus:
    """Recompute the tenant's chain now. Cost grows with the log; fine at on-prem volumes."""
    database: Database = request.app.state.database
    tenant_id = request.app.state.tenant_id
    async with database.tenant_transaction(tenant_id) as connection:
        result = await audit.verify(connection, tenant_id)
    return ChainStatus(ok=result.ok, events_checked=result.events_checked, problem=result.problem)
