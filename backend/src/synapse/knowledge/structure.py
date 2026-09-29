"""The structure of a document: the blocks its pages are made of (ADR 0010, ingestion 5 and 7).

Parsers produce blocks in reading order; chunking consumes them. A block carries the page it
is on, so every chunk, and every citation, resolves to a page.

- ``heading``: a section title, with its ``level`` (1 is the outermost). Levels come from the
  document's own conventions (knowledge/headings.py), not from font sizes.
- ``paragraph``, ``list_item``, ``caption``, ``footnote``: running text. A paragraph can open a
  section too (``level`` set): Turkish legislation writes "Madde 5- ..." as the first words of
  the article's own text, not as a separate title.
- ``figure_text``: text inside a figure, such as the boxes of a flowchart. Layout parsers tend
  to drop it with the figure; it is often the page's whole content.
- ``table``: cell text in rows. A cell spanning several columns or rows keeps its text in its
  first position only, so it is not repeated once per column it covers.
"""

from dataclasses import dataclass, field
from typing import Any, Literal, cast

BlockKind = Literal[
    "heading", "paragraph", "list_item", "caption", "footnote", "figure_text", "table"
]


@dataclass(frozen=True)
class Table:
    rows: tuple[tuple[str, ...], ...]
    # Leading rows that label the columns; repeated on every chunk a large table is split into.
    header_rows: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.header_rows <= len(self.rows):
            raise ValueError("header_rows outside the table")

    @property
    def header(self) -> tuple[tuple[str, ...], ...]:
        return self.rows[: self.header_rows]

    @property
    def body(self) -> tuple[tuple[str, ...], ...]:
        return self.rows[self.header_rows :]


@dataclass(frozen=True)
class Block:
    kind: BlockKind
    text: str
    page: int
    level: int | None = None
    # For a paragraph that opens a section: the short label for the heading path ("Madde 5").
    label: str | None = None
    table: Table | None = field(default=None, compare=True)

    def __post_init__(self) -> None:
        if (self.kind == "table") != (self.table is not None):
            raise ValueError("a table block needs a table, and only a table block has one")
        if self.kind == "heading" and self.level is None:
            raise ValueError("a heading needs a level")
        if self.level is not None and self.level < 1:
            raise ValueError("levels start at 1")

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind, "text": self.text, "page": self.page}
        if self.level is not None:
            data["level"] = self.level
        if self.label is not None:
            data["label"] = self.label
        if self.table is not None:
            data["rows"] = [list(row) for row in self.table.rows]
            data["header_rows"] = self.table.header_rows
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Block:
        table = None
        if "rows" in data:
            table = Table(tuple(tuple(row) for row in data["rows"]), data.get("header_rows", 0))
        return cls(
            kind=cast("BlockKind", data["kind"]),
            text=data["text"],
            page=data["page"],
            level=data.get("level"),
            label=data.get("label"),
            table=table,
        )


def row_text(row: tuple[str, ...]) -> str:
    """One table row as a line: its non-empty cells joined by " | "."""
    return " | ".join(cell for cell in row if cell)


def table_text(table: Table) -> str:
    return "\n".join(line for line in map(row_text, table.rows) if line)
