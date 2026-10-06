"""The scope of a search or an answer: the folders and documents the user chose to draw on.

A scope narrows what the user may read; it never widens it. Every statement that applies one
still starts from ``accessible_documents``, and a folder or document the user may not read, or
that does not exist, simply matches nothing. A folder brings every folder inside it. The empty
scope is everything the user may read.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

# How much a scope may name: the screen offers a few folders or documents, not a catalogue.
MAX_COLLECTIONS = 50
MAX_DOCUMENTS = 200

# The chosen folders and every folder inside them, as the first part of a statement; ``IN_SCOPE``
# reads it. The statements are built from constant fragments; every value is a parameter.
CHOSEN = (
    "WITH RECURSIVE chosen (id) AS ("
    "SELECT unnest(%(collections)s::uuid[]) "
    "UNION SELECT c.id FROM collections c JOIN chosen ON c.parent_id = chosen.id) "
)
# Whether the document ``d`` is in the scope.
IN_SCOPE = (
    "(%(everything)s OR d.id = ANY(%(documents)s::uuid[]) "
    "OR d.collection_id IN (SELECT id FROM chosen))"
)


@dataclass(frozen=True)
class Scope:
    collections: tuple[UUID, ...] = ()
    documents: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        if len(self.collections) > MAX_COLLECTIONS or len(self.documents) > MAX_DOCUMENTS:
            raise ValueError("a scope names too many folders or documents")

    @property
    def everything(self) -> bool:
        return not self.collections and not self.documents

    def parameters(self) -> dict[str, Any]:
        """The values ``CHOSEN`` and ``IN_SCOPE`` read."""
        return {
            "everything": self.everything,
            "collections": list(self.collections),
            "documents": list(self.documents),
        }

    def as_json(self) -> dict[str, list[str]]:
        """As a conversation keeps it; the empty scope is an empty object."""
        if self.everything:
            return {}
        return {
            "collections": [str(c) for c in self.collections],
            "documents": [str(d) for d in self.documents],
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any] | None) -> Scope:
        data = data or {}
        return cls(
            tuple(dict.fromkeys(UUID(str(c)) for c in data.get("collections", []))),
            tuple(dict.fromkeys(UUID(str(d)) for d in data.get("documents", []))),
        )


EVERYTHING = Scope()
