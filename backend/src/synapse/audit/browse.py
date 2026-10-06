"""Reading the audit log back: the auditor's screen and its exports (ADR 0008).

Events are listed newest first, a page at a time, filtered by time, action, actor, target and
outcome. Two exports of the same filter, oldest event first:

- CSV for a spreadsheet: semicolons and a byte order mark, as Excel opens it in Turkish.
- JSON signed with the instance's Ed25519 key. It keeps every column of every event, the chain
  hashes included, so that whoever holds the public key can check away from the machine that
  the file is the one Synapse wrote (the signature over the manifest, whose ``events_sha256``
  covers each event's canonical form) and recompute each event's hash (``chain.event_hash``).
"""

import base64
import csv
import hashlib
import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from psycopg import AsyncConnection

from synapse.audit.canonical import JsonValue, canonical_bytes
from synapse.audit.chain import Outcome

MAX_PAGE = 200
# An export holds at most this many events; a wider one is refused, to be narrowed by time.
MAX_EXPORT = 50_000
EXPORT_FORMAT = 1
CSV_COLUMNS = (
    "seq",
    "occurred_at",
    "actor_name",
    "actor_email",
    "actor_user_id",
    "actor_ip",
    "action",
    "target_type",
    "target_id",
    "outcome",
    "details",
    "hash",
)

# The statements are built from constant fragments; every value is a parameter.
_SELECT = (
    "SELECT e.seq, e.id, e.occurred_at, e.actor_user_id, u.display_name, u.email, e.actor_ip, "
    "e.action, e.target_type, e.target_id, e.outcome, e.details, e.schema_version, "
    "e.prev_hash, e.hash FROM audit_events e LEFT JOIN users u ON u.id = e.actor_user_id "
    "WHERE e.tenant_id = %(tenant)s "
)


class TooManyEventsError(ValueError):
    """The export would hold more than ``MAX_EXPORT`` events."""


@dataclass(frozen=True)
class EventFilter:
    since: datetime | None = None
    until: datetime | None = None
    # One action ("identity.login"), or a family of them ending in a dot ("identity.").
    action: str | None = None
    actor_user_id: UUID | None = None
    target_type: str | None = None
    target_id: str | None = None
    outcome: Outcome | None = None

    def clauses(self) -> tuple[str, dict[str, Any]]:
        """The conditions after ``_SELECT``'s tenant, and their parameters."""
        parts: list[str] = []
        values: dict[str, Any] = {}
        if self.since is not None:
            parts.append("AND e.occurred_at >= %(since)s ")
            values["since"] = self.since
        if self.until is not None:
            parts.append("AND e.occurred_at < %(until)s ")
            values["until"] = self.until
        if self.action is not None:
            if self.action.endswith("."):
                parts.append("AND starts_with(e.action, %(action)s) ")
            else:
                parts.append("AND e.action = %(action)s ")
            values["action"] = self.action
        for name in ("actor_user_id", "target_type", "target_id", "outcome"):
            value = getattr(self, name)
            if value is not None:
                parts.append(f"AND e.{name} = %({name})s ")
                values[name] = value
        return "".join(parts), values

    def as_json(self) -> dict[str, str]:
        """The filter as an export names it: the conditions given, as text."""
        given = {
            "since": self.since.isoformat() if self.since else None,
            "until": self.until.isoformat() if self.until else None,
            "action": self.action,
            "actor_user_id": str(self.actor_user_id) if self.actor_user_id else None,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "outcome": self.outcome,
        }
        return {key: value for key, value in given.items() if value is not None}


@dataclass(frozen=True)
class StoredEvent:
    seq: int
    id: UUID
    occurred_at: datetime
    actor_user_id: UUID | None
    # The actor's name and address as they are now (None for the system, or a removed user).
    actor_name: str | None
    actor_email: str | None
    actor_ip: str | None
    action: str
    target_type: str | None
    target_id: str | None
    outcome: str
    details: Mapping[str, JsonValue]
    schema_version: int
    prev_hash: str
    hash: str

    def as_json(self) -> dict[str, JsonValue]:
        return {
            "seq": self.seq,
            "id": str(self.id),
            "occurred_at": self.occurred_at.isoformat(),
            "actor_user_id": str(self.actor_user_id) if self.actor_user_id else None,
            "actor_name": self.actor_name,
            "actor_email": self.actor_email,
            "actor_ip": self.actor_ip,
            "action": self.action,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "outcome": self.outcome,
            "details": dict(self.details),
            "schema_version": self.schema_version,
            "prev_hash": self.prev_hash,
            "hash": self.hash,
        }


async def list_events(
    connection: AsyncConnection,
    tenant_id: UUID,
    where: EventFilter,
    *,
    before: int | None = None,
    limit: int = MAX_PAGE,
) -> list[StoredEvent]:
    """A page of events, newest first; ``before`` a sequence number to continue below."""
    clauses, values = where.clauses()
    if before is not None:
        clauses += "AND e.seq < %(before)s "
        values["before"] = before
    cursor = await connection.execute(
        _SELECT + clauses + "ORDER BY e.seq DESC LIMIT %(limit)s",
        {"tenant": tenant_id, "limit": min(limit, MAX_PAGE), **values},
    )
    return [_event(row) for row in await cursor.fetchall()]


async def export_events(
    connection: AsyncConnection, tenant_id: UUID, where: EventFilter, *, limit: int = MAX_EXPORT
) -> list[StoredEvent]:
    """Every event the filter selects, oldest first; ``TooManyEventsError`` past ``limit``."""
    clauses, values = where.clauses()
    cursor = await connection.execute(
        _SELECT + clauses + "ORDER BY e.seq LIMIT %(limit)s",
        {"tenant": tenant_id, "limit": limit + 1, **values},
    )
    rows = await cursor.fetchall()
    if len(rows) > limit:
        raise TooManyEventsError(f"more than {limit} events")
    return [_event(row) for row in rows]


def as_csv(events: Sequence[StoredEvent]) -> str:
    """Semicolons and a byte order mark: what Excel opens as columns in a Turkish locale."""
    buffer = io.StringIO()
    buffer.write("﻿")
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for event in events:
        row = event.as_json()
        row["details"] = canonical_bytes(event.details).decode("utf-8")
        writer.writerow([_cell(row[c]) for c in CSV_COLUMNS])
    return buffer.getvalue()


# What a spreadsheet takes for the start of a formula, full-width forms included. A display
# name like "=HYPERLINK(...)" would otherwise run when the auditor opens the file (OWASP's
# CSV injection).
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r", "\uff1d", "\uff0b", "\uff0d", "\uff20")


def _cell(value: JsonValue) -> JsonValue:
    """A value as a CSV cell: text that would start a formula is kept as text, behind a quote."""
    if value is None:
        return ""
    if isinstance(value, str) and value.startswith(_FORMULA_STARTS):
        return "'" + value
    return value


def signed_export(
    key: Ed25519PrivateKey,
    tenant_id: UUID,
    where: EventFilter,
    events: Sequence[StoredEvent],
    now: datetime,
) -> dict[str, Any]:
    """The events with a manifest and the manifest's signature (see the module's docstring)."""
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    manifest: dict[str, JsonValue] = {
        "format": EXPORT_FORMAT,
        "tenant_id": str(tenant_id),
        "exported_at": now.isoformat(),
        "filter": dict(where.as_json()),
        "count": len(events),
        "first_seq": events[0].seq if events else None,
        "last_seq": events[-1].seq if events else None,
        "events_sha256": _events_digest([e.as_json() for e in events]),
        "public_key": base64.b64encode(public).decode("ascii"),
    }
    signature = key.sign(canonical_bytes(manifest))
    return {
        "manifest": manifest,
        "signature": base64.b64encode(signature).decode("ascii"),
        "events": [event.as_json() for event in events],
    }


def export_is_authentic(document: Mapping[str, Any], public_key: Ed25519PublicKey) -> bool:
    """Whether a signed export is whole and signed with this key (the public key comes from
    the installation, not from the file)."""
    manifest = document.get("manifest")
    events = document.get("events")
    if not isinstance(manifest, Mapping) or not isinstance(events, list):
        return False
    if manifest.get("events_sha256") != _events_digest(events):
        return False
    if manifest.get("count") != len(events):
        return False
    try:
        public_key.verify(
            base64.b64decode(str(document.get("signature", ""))), canonical_bytes(manifest)
        )
    except InvalidSignature, ValueError:
        return False
    return True


def _events_digest(events: Sequence[Mapping[str, JsonValue]]) -> str:
    digest = hashlib.sha256()
    for event in events:
        digest.update(canonical_bytes(event))
        digest.update(b"\n")
    return digest.hexdigest()


def _event(row: Sequence[Any]) -> StoredEvent:
    return StoredEvent(
        seq=int(row[0]),
        id=row[1],
        occurred_at=row[2],
        actor_user_id=row[3],
        actor_name=row[4],
        actor_email=row[5],
        actor_ip=None if row[6] is None else str(row[6]),
        action=row[7],
        target_type=row[8],
        target_id=row[9],
        outcome=row[10],
        details=row[11],
        schema_version=int(row[12]),
        prev_hash=bytes(row[13]).hex(),
        hash=bytes(row[14]).hex(),
    )
