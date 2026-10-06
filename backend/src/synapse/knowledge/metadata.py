"""A document's metadata: its kind, its date, its number and its tags (v1 scope).

When a version has been read, its kind, date and number are suggested from what the document
says about itself: the title and the head of the first page, where a decision, a regulation or
a report names itself, carries its date and its number. The kind is the earliest of the
language's kind words there (knowledge/data, ``document_kinds``), the title first; the date
and the number are the first ``date`` and ``decision_number`` entities of the head
(entities.py). Tags come only from people.

A person may set or correct any of them (``DocumentService.update_metadata``); a field a person
set is never replaced by a suggestion again (``documents.metadata_set_by_hand``), so a new
version updates only what nobody touched.
"""

import datetime
import re
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from psycopg import AsyncConnection

from synapse.knowledge.entities import extract
from synapse.knowledge.language import language
from synapse.knowledge.turkish import lower

# The head of the first page: where a document names itself, dates and numbers itself.
HEAD_CHARS = 1500
# The fields suggestions fill, by their column.
SUGGESTED = ("kind", "document_date", "reference")
# What a person may set on a document, in the order they are written.
FIELDS = ("title", "tags", *SUGGESTED)
# The longest of each text, as the columns allow (migrations 0005 and 0026).
MAX_LENGTH = {"title": 500, "kind": 80, "reference": 120, "tag": 50}
MAX_TAGS = 20


class InvalidMetadataError(ValueError):
    """A field that is not metadata, or a value it cannot hold."""


def checked(changes: Mapping[str, object]) -> dict[str, object]:
    """The changes as they are stored: texts trimmed, an empty kind or number cleared, tags
    trimmed and each once. A wrong field or value raises ``InvalidMetadataError``."""
    unknown = sorted(set(changes) - set(FIELDS))
    if unknown or not changes:
        raise InvalidMetadataError(f"not metadata: {unknown}")
    result: dict[str, object] = {}
    for name in FIELDS:
        if name not in changes:
            continue
        value = changes[name]
        if name == "tags":
            result[name] = _tags(value)
        elif name == "document_date":
            if value is not None and not isinstance(value, datetime.date):
                raise InvalidMetadataError("document_date is a date")
            result[name] = value
        else:
            text = _text(name, value)
            if text is None and name == "title":
                raise InvalidMetadataError("a document has a title")
            result[name] = text
    return result


def _text(name: str, value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidMetadataError(f"{name} is text")
    text = " ".join(value.split())
    if len(text) > MAX_LENGTH[name]:
        raise InvalidMetadataError(f"{name} is too long")
    return text or None


def _tags(value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        raise InvalidMetadataError("tags are a list")
    tags: list[str] = []
    for item in value:
        tag = _text("tag", item)
        if tag is not None and tag not in tags:
            tags.append(tag)
    if len(tags) > MAX_TAGS:
        raise InvalidMetadataError("too many tags")
    return tags


@dataclass(frozen=True)
class Suggested:
    kind: str | None
    document_date: datetime.date | None
    reference: str | None


def suggest(title: str, first_page: str) -> Suggested:
    head = first_page[:HEAD_CHARS]
    kind = _kind(title) or _kind(head)
    entities = extract(head)
    dates = [e.value for e in entities if e.kind == "date"]
    numbers = [e.value for e in entities if e.kind == "decision_number"]
    return Suggested(
        kind=kind,
        document_date=datetime.date.fromisoformat(dates[0]) if dates else None,
        reference=numbers[0] if numbers else None,
    )


def _kind(text: str) -> str | None:
    """The kind named earliest in ``text``; at the same place, the longer word ("kararname"
    before "karar")."""
    folded = lower(text)
    found: list[tuple[int, int, str]] = []
    for word, label in language().document_kinds:
        match = re.search(rf"(?<!\w){re.escape(word)}", folded)
        if match is not None:
            found.append((match.start(), -len(word), label))
    return min(found)[2] if found else None


async def apply_suggestions(
    connection: AsyncConnection, document_id: UUID, version_id: UUID
) -> Suggested | None:
    """Suggest the document's metadata from this version, when it is the newest; fields a
    person set stay as they are."""
    cursor = await connection.execute(
        "SELECT d.title, (SELECT p.text FROM document_pages p WHERE p.version_id = %s "
        "ORDER BY p.number LIMIT 1) "
        "FROM documents d WHERE d.id = %s AND %s = (SELECT dv.id FROM document_versions dv "
        "WHERE dv.document_id = d.id ORDER BY dv.version DESC LIMIT 1)",
        (version_id, document_id, version_id),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    suggested = suggest(row[0], row[1] or "")
    await connection.execute(
        "UPDATE documents SET "
        "kind = CASE WHEN 'kind' = ANY(metadata_set_by_hand) THEN kind ELSE %s END, "
        "document_date = CASE WHEN 'document_date' = ANY(metadata_set_by_hand) "
        "THEN document_date ELSE %s END, "
        "reference = CASE WHEN 'reference' = ANY(metadata_set_by_hand) THEN reference "
        "ELSE %s END "
        "WHERE id = %s",
        (suggested.kind, suggested.document_date, suggested.reference, document_id),
    )
    return suggested
