"""Audit endpoints under ``/api/audit``, for the auditor role (ADR 0008).

``/status`` recomputes the chain and compares the kept checkpoints with it; ``/events`` lists
events newest first, a page at a time; ``/export`` writes the events a filter selects as CSV or
as JSON signed with the instance's key (audit/browse.py). Every export is itself audited.
"""

import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import AwareDatetime, BaseModel

from synapse.api.deps import ApiError, client_ip, require
from synapse.audit import public as audit
from synapse.identity.public import CurrentSession
from synapse.kernel.database import Database
from synapse.kernel.secrets import SecretError

router = APIRouter(prefix="/api/audit", tags=["audit"])

AuditReader = Annotated[CurrentSession, require("audit.read")]
# An action, or a family of actions ending in a dot: "identity.login", "identity.".
ACTION = r"^[a-z_]+(\.[a-z_]+)*\.?$"


class ChainStatus(BaseModel):
    ok: bool
    events_checked: int
    problem: str | None
    # Signed checkpoints compared with the chain; 0 when the signing key cannot be read here.
    checkpoints_checked: int = 0


class EventView(BaseModel):
    seq: int
    id: UUID
    occurred_at: datetime
    actor_user_id: UUID | None
    actor_name: str | None
    actor_email: str | None
    actor_ip: str | None
    action: str
    target_type: str | None
    target_id: str | None
    outcome: str
    details: dict[str, object]


class EventPage(BaseModel):
    events: list[EventView]
    # Pass as ``before`` for the next page; None on the last.
    next_before: int | None


def event_filter(  # noqa: PLR0913, PLR0917  (one argument per query parameter)
    since: AwareDatetime | None = None,
    until: AwareDatetime | None = None,
    action: Annotated[str | None, Query(max_length=100, pattern=ACTION)] = None,
    actor: UUID | None = None,
    target_type: Annotated[str | None, Query(max_length=64)] = None,
    target_id: Annotated[str | None, Query(max_length=200)] = None,
    outcome: Literal["success", "failure", "denied"] | None = None,
) -> audit.EventFilter:
    return audit.EventFilter(since, until, action, actor, target_type, target_id, outcome)


Filter = Annotated[audit.EventFilter, Depends(event_filter)]


def _signing_key(request: Request) -> Ed25519PrivateKey | None:
    try:
        return audit.load_signing_key(request.app.state.audit_signing_key_file)
    except SecretError, OSError:
        return None


@router.get("/status", dependencies=[require("audit.read")])
async def chain_status(request: Request) -> ChainStatus:
    """Recompute the tenant's chain now. Cost grows with the log; fine at on-prem volumes."""
    database: Database = request.app.state.database
    tenant_id = request.app.state.tenant_id
    key = _signing_key(request)
    async with database.tenant_transaction(tenant_id) as connection:
        result = await audit.verify(connection, tenant_id)
        if not result.ok or key is None:
            return ChainStatus(
                ok=result.ok, events_checked=result.events_checked, problem=result.problem
            )
        kept = await audit.verify_checkpoints(connection, tenant_id, key.public_key())
    return ChainStatus(
        ok=kept.problem is None,
        events_checked=result.events_checked,
        problem=kept.problem,
        checkpoints_checked=kept.checked,
    )


@router.get("/events", dependencies=[require("audit.read")])
async def events(
    request: Request,
    where: Filter,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=audit.MAX_PAGE)] = 50,
) -> EventPage:
    database: Database = request.app.state.database
    tenant_id = request.app.state.tenant_id
    async with database.tenant_transaction(tenant_id) as connection:
        found = await audit.list_events(connection, tenant_id, where, before=before, limit=limit)
    return EventPage(
        events=[EventView(**_view(event)) for event in found],
        next_before=found[-1].seq if len(found) == limit else None,
    )


@router.get("/export")
async def export(
    session: AuditReader,
    request: Request,
    where: Filter,
    format: Literal["csv", "json"] = "csv",  # noqa: A002  (the query parameter's name)
) -> Response:
    database: Database = request.app.state.database
    tenant_id = request.app.state.tenant_id
    key = _signing_key(request) if format == "json" else None
    if format == "json" and key is None:
        raise ApiError(status.HTTP_503_SERVICE_UNAVAILABLE, "signing_key_unavailable")
    now = datetime.now(UTC)
    async with database.tenant_transaction(tenant_id) as connection:
        try:
            found = await audit.export_events(connection, tenant_id, where)
        except audit.TooManyEventsError as error:
            raise ApiError(status.HTTP_413_CONTENT_TOO_LARGE, "too_many_events") from error
        await audit.record(
            connection,
            tenant_id,
            audit.AuditEvent(
                "audit.export",
                "success",
                actor_user_id=session.user_id,
                actor_ip=client_ip(request),
                details={"format": format, "count": len(found), **where.as_json()},
            ),
            now,
        )
    stamp = now.strftime("%Y%m%d-%H%M%S")
    if key is not None:
        document = audit.signed_export(key, tenant_id, where, found, now)
        return Response(
            json.dumps(document, ensure_ascii=False, indent=1),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="audit-{stamp}.json"'},
        )
    return Response(
        audit.as_csv(found).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="audit-{stamp}.csv"'},
    )


def _view(event: audit.StoredEvent) -> dict[str, object]:
    shown: dict[str, object] = dict(event.as_json())
    for internal in ("schema_version", "prev_hash", "hash"):
        shown.pop(internal)
    return shown
