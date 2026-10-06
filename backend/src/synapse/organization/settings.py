"""The organisation's settings: choices an administrator makes for everyone (v1 scope).

One row per tenant (``tenant_settings``, migration 0025), validated here: an unknown key or a
value out of range is refused, never stored to be ignored later. A change sets only the keys it
sends. Every change is audited with the keys it changed and their new values (for synonyms,
how many groups there are). Other packages read the keys they own from the row (identity:
``mfa_required_roles``; knowledge: ``synonyms``), with the same defaults as here.
"""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from synapse.audit import public as audit
from synapse.kernel.database import Database
from synapse.knowledge.public import lower

# Roles that may be asked to use a second factor; administrators always must (ADR 0006).
OptionalMfaRole = Literal["editor", "member", "auditor"]

MAX_SYNONYM_GROUPS = 200
MIN_PHRASES = 2
Phrase = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
SynonymGroup = Annotated[list[Phrase], Field(min_length=MIN_PHRASES, max_length=10)]


class OrganizationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Roles that must sign in with a second factor, besides administrators.
    mfa_required_roles: list[OptionalMfaRole] = Field(default_factory=list, max_length=3)
    # Phrases that mean the same, abbreviations among them ("KVKK", "Kişisel Verilerin
    # Korunması Kanunu"): a question that names one is searched for with the others too
    # (ADR 0010, query rule 1; knowledge/search.py, ``with_synonyms``).
    synonyms: list[SynonymGroup] = Field(default_factory=list, max_length=MAX_SYNONYM_GROUPS)

    @field_validator("synonyms")
    @classmethod
    def _distinct(cls, groups: list[list[str]]) -> list[list[str]]:
        """Spaces collapsed; each phrase once in its group, whatever its case, and in one group
        only, so a question never brings two groups for one phrase."""
        seen: set[str] = set()
        distinct: list[list[str]] = []
        for group in groups:
            phrases: dict[str, str] = {}
            for phrase in group:
                text = " ".join(phrase.split())
                if not any(ch.isalnum() for ch in text):
                    raise ValueError(f"{text!r} has neither a letter nor a digit")
                if lower(text) in seen:
                    raise ValueError(f"{text!r} is in two groups")
                phrases.setdefault(lower(text), text)
            if len(phrases) < MIN_PHRASES:
                raise ValueError(f"{group[0]!r} has no other phrase in its group")
            seen.update(phrases)
            distinct.append(list(phrases.values()))
        return distinct


class SettingsService:
    def __init__(self, database: Database, *, tenant_id: UUID) -> None:
        self._db = database
        self._tenant_id = tenant_id

    async def get(self) -> OrganizationSettings:
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            return await _read(connection)

    async def update(
        self, settings: OrganizationSettings, *, user_id: UUID, ip: str | None, now: datetime
    ) -> OrganizationSettings:
        """Store the settings sent (``model_fields_set``), the others staying as they are;
        audited with what changed (nothing changed, nothing recorded)."""
        async with self._db.tenant_transaction(self._tenant_id) as connection:
            current = await _read(connection, lock=True)
            sent = {name: getattr(settings, name) for name in settings.model_fields_set}
            stored = current.model_copy(update=sent)
            stored = stored.model_copy(
                update={"mfa_required_roles": sorted(set(stored.mfa_required_roles))}
            )
            before = current.model_dump()
            after = stored.model_dump()
            changed: dict[str, Any] = {
                k: _summary(k, v) for k, v in after.items() if before.get(k) != v
            }
            if not changed:
                return stored
            await connection.execute(
                "INSERT INTO tenant_settings (tenant_id, settings, updated_at, updated_by) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (tenant_id) DO UPDATE SET "
                "settings = EXCLUDED.settings, updated_at = EXCLUDED.updated_at, "
                "updated_by = EXCLUDED.updated_by",
                (self._tenant_id, Jsonb(after), now, user_id),
            )
            await audit.record(
                connection,
                self._tenant_id,
                audit.AuditEvent(
                    "org.settings.change",
                    "success",
                    actor_user_id=user_id,
                    actor_ip=ip,
                    details={"changed": changed},
                ),
                now,
            )
        return stored


def _summary(key: str, value: Any) -> Any:
    """What the audit log keeps of a new value: synonyms by their number, the rest whole."""
    return {"groups": len(value)} if key == "synonyms" else value


_READ = "SELECT settings FROM tenant_settings"
_READ_FOR_UPDATE = _READ + " FOR UPDATE"


async def _read(connection: AsyncConnection, *, lock: bool = False) -> OrganizationSettings:
    cursor = await connection.execute(_READ_FOR_UPDATE if lock else _READ)
    row = await cursor.fetchone()
    return OrganizationSettings.model_validate(row[0] if row else {})
