"""Writing and verifying the per-tenant audit hash chain (ADR 0008).

Each event's hash covers every stored column except the hash itself, in canonical form, and
includes the previous event's hash. Verification recomputes each hash from the row's contents;
comparing stored hashes with each other would prove nothing, because a forger can store any
value they like.
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv6Address
from typing import Literal
from uuid import UUID, uuid4

from psycopg import AsyncConnection

from synapse.audit.canonical import JsonValue, canonical_bytes

SCHEMA_VERSION = 1
GENESIS_HASH = bytes(32)
Outcome = Literal["success", "failure", "denied"]


@dataclass(frozen=True)
class AuditEvent:
    """Something that happened, to be appended to the tenant's chain."""

    action: str
    outcome: Outcome
    actor_user_id: UUID | None = None
    actor_ip: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    details: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class ChainHead:
    tenant_id: UUID
    seq: int
    hash: bytes


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    events_checked: int
    problem: str | None = None
    # Signed checkpoints compared with the chain (synapse audit verify, with the signing key).
    checkpoints_checked: int = 0


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def event_hash(  # noqa: PLR0913  (one argument per hashed column)
    *,
    tenant_id: UUID,
    seq: int,
    event_id: UUID,
    occurred_at: datetime,
    event: AuditEvent,
    schema_version: int,
    prev_hash: bytes,
) -> bytes:
    document: dict[str, JsonValue] = {
        "tenant_id": str(tenant_id),
        "seq": seq,
        "id": str(event_id),
        "occurred_at": _timestamp(occurred_at),
        "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
        "actor_ip": event.actor_ip,
        "action": event.action,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "outcome": event.outcome,
        "details": event.details,
        "schema_version": schema_version,
        "prev_hash": prev_hash.hex(),
    }
    return hashlib.sha256(canonical_bytes(document)).digest()


async def record(
    connection: AsyncConnection, tenant_id: UUID, event: AuditEvent, now: datetime
) -> ChainHead:
    """Append ``event`` inside the caller's transaction.

    The advisory lock makes this tenant's chain single-writer until the transaction ends, so two
    concurrent events cannot both claim the same sequence number or fork the chain. If the
    caller's transaction rolls back, the event disappears with the action it describes.
    """
    await connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended('synapse.audit:' || %s::text, 0))",
        (tenant_id,),
    )
    cursor = await connection.execute(
        "SELECT seq, hash FROM audit_events WHERE tenant_id = %s ORDER BY seq DESC LIMIT 1",
        (tenant_id,),
    )
    last = await cursor.fetchone()
    seq, prev_hash = (int(last[0]) + 1, bytes(last[1])) if last else (1, GENESIS_HASH)
    # Python and PostgreSQL both keep microseconds, so the stored value hashes identically.
    occurred_at = now.astimezone(UTC)
    event_id = uuid4()
    digest = event_hash(
        tenant_id=tenant_id,
        seq=seq,
        event_id=event_id,
        occurred_at=occurred_at,
        event=event,
        schema_version=SCHEMA_VERSION,
        prev_hash=prev_hash,
    )
    await connection.execute(
        "INSERT INTO audit_events (tenant_id, seq, id, occurred_at, actor_user_id, actor_ip, "
        "action, target_type, target_id, outcome, details, schema_version, prev_hash, hash) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)",
        (
            tenant_id,
            seq,
            event_id,
            occurred_at,
            event.actor_user_id,
            event.actor_ip,
            event.action,
            event.target_type,
            event.target_id,
            event.outcome,
            canonical_bytes(dict(event.details)).decode("utf-8"),
            SCHEMA_VERSION,
            prev_hash,
            digest,
        ),
    )
    return ChainHead(tenant_id=tenant_id, seq=seq, hash=digest)


async def head(connection: AsyncConnection, tenant_id: UUID) -> ChainHead | None:
    cursor = await connection.execute(
        "SELECT seq, hash FROM audit_events WHERE tenant_id = %s ORDER BY seq DESC LIMIT 1",
        (tenant_id,),
    )
    row = await cursor.fetchone()
    return ChainHead(tenant_id, int(row[0]), bytes(row[1])) if row else None


def _ip_text(value: IPv4Address | IPv6Address | str | None) -> str | None:
    return None if value is None else str(value)


async def verify(connection: AsyncConnection, tenant_id: UUID) -> VerificationResult:
    """Recompute the whole chain. Stops at the first problem and reports where it is."""
    expected_prev = GENESIS_HASH
    checked = 0
    async with connection.cursor(name="audit_verify") as cursor:
        await cursor.execute(
            "SELECT seq, id, occurred_at, actor_user_id, actor_ip, action, target_type, "
            "target_id, outcome, details, schema_version, prev_hash, hash "
            "FROM audit_events WHERE tenant_id = %s ORDER BY seq",
            (tenant_id,),
        )
        async for row in cursor:
            seq = int(row[0])
            if seq != checked + 1:
                return VerificationResult(
                    ok=False, events_checked=checked, problem=f"sequence gap before event {seq}"
                )
            if bytes(row[11]) != expected_prev:
                return VerificationResult(
                    ok=False,
                    events_checked=checked,
                    problem=f"event {seq} does not link to {seq - 1}",
                )
            recomputed = event_hash(
                tenant_id=tenant_id,
                seq=seq,
                event_id=row[1],
                occurred_at=row[2],
                event=AuditEvent(
                    action=row[5],
                    outcome=row[8],
                    actor_user_id=row[3],
                    actor_ip=_ip_text(row[4]),
                    target_type=row[6],
                    target_id=row[7],
                    details=row[9],
                ),
                schema_version=int(row[10]),
                prev_hash=bytes(row[11]),
            )
            if recomputed != bytes(row[12]):
                return VerificationResult(
                    ok=False, events_checked=checked, problem=f"event {seq} was modified"
                )
            expected_prev = recomputed
            checked += 1
    return VerificationResult(ok=True, events_checked=checked)
