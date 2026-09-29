"""A DoclingDocument (its JSON export) as Synapse blocks (backend/src/synapse/knowledge/
structure.py), so the same chunker reads both parsers. Pure Python: it reads the JSON only.

- Reading order is the document's ``body`` tree; groups (lists) are walked through.
- Page headers and footers are dropped; Docling marks them.
- Headings get their level from the Turkish rules (knowledge/headings.py): Docling marks
  headings but gives them all the same level. A "heading" longer than a title, or ending like a
  sentence, is taken as a paragraph.
- A list item's marker ("(1)", "a)"), which Docling keeps apart from its text, is put back.
- Text inside a figure (a flowchart's boxes) becomes one figure-text block.
- A table becomes rows of cells; a spanning cell keeps its text in its first position; leading
  rows whose cells are all column headers are the header rows.
"""

from typing import Any

from synapse.knowledge.headings import MAX_HEADING_CHARS, section
from synapse.knowledge.structure import Block, BlockKind, Table

SKIPPED = {"page_header", "page_footer"}
KINDS: dict[str, BlockKind] = {
    "list_item": "list_item",
    "caption": "caption",
    "footnote": "footnote",
}


def blocks_from_run(saved: dict[str, Any]) -> list[Block]:
    """Blocks of a document written by run.py: its page batches, in order."""
    return [block for doc in saved["batches"] for block in blocks_from_docling(doc)]


def blocks_from_docling(doc: dict[str, Any]) -> list[Block]:
    return _Converter(doc).blocks()


def _clean(text: str) -> str:
    return " ".join(text.split())


class _Converter:
    def __init__(self, doc: dict[str, Any]) -> None:
        self.doc = doc
        self.items = {name: doc[name] for name in ("texts", "groups", "tables", "pictures")}
        # The page of the last item that had one; a batch starts at its own first page.
        self.page = min((int(number) for number in doc.get("pages", {})), default=1)
        self.out: list[Block] = []

    def blocks(self) -> list[Block]:
        for child in self.doc["body"]["children"]:
            self.walk(child)
        return self.out

    def resolve(self, ref: dict[str, str]) -> tuple[str, dict[str, Any]]:
        _, name, index = ref["$ref"].split("/")
        return name, self.items[name][int(index)]

    def page_of(self, item: dict[str, Any]) -> int:
        if item.get("prov"):
            self.page = item["prov"][0]["page_no"]
        return self.page

    def walk(self, ref: dict[str, str]) -> None:
        name, item = self.resolve(ref)
        if item.get("content_layer") == "furniture":
            return
        block = None
        if name == "texts":
            block = self.text_block(item)
        elif name == "tables":
            block = self.table_block(item)
        elif name == "pictures":
            block = self.figure_block(item)
        if block is not None:
            self.out.append(block)
        if name in ("groups", "texts"):
            for child in item.get("children", []):
                self.walk(child)

    def text_block(self, item: dict[str, Any]) -> Block | None:
        label = item["label"]
        text = _clean(item.get("text", ""))
        marker = _clean(item.get("marker", ""))
        if marker and text and not text.startswith(marker):
            text = f"{marker} {text}"
        if not text or label in SKIPPED:
            return None
        number = self.page_of(item)
        if label in ("title", "section_header"):
            sentence = len(text) > MAX_HEADING_CHARS or text.endswith((".", ";", ","))
            marked = section(text, marked=True)
            if not sentence and marked is not None:
                return Block("heading", text, number, level=marked.level)
        found = section(text, marked=False)
        if found is not None and not found.running:
            return Block("heading", text, number, level=found.level)
        kind = KINDS.get(label, "paragraph")
        if found is not None:
            return Block(kind, text, number, level=found.level, label=found.label)
        return Block(kind, text, number)

    def table_block(self, item: dict[str, Any]) -> Block | None:
        data = item["data"]
        rows = [[""] * data["num_cols"] for _ in range(data["num_rows"])]
        header = [True] * data["num_rows"]
        for cell in data["table_cells"]:
            r, c = cell["start_row_offset_idx"], cell["start_col_offset_idx"]
            if r < len(rows) and c < len(rows[r]):
                rows[r][c] = _clean(cell["text"])
            if not cell.get("column_header"):
                for spanned in range(cell["start_row_offset_idx"], cell["end_row_offset_idx"]):
                    if spanned < len(header):
                        header[spanned] = False
        if not any(any(row) for row in rows):
            return None
        header_rows = 0
        while header_rows < len(rows) - 1 and header[header_rows]:
            header_rows += 1
        table = Table(tuple(map(tuple, rows)), header_rows)
        return Block("table", "", self.page_of(item), table=table)

    def figure_block(self, item: dict[str, Any]) -> Block | None:
        number = self.page_of(item)
        texts = []
        for child in item.get("children", []):
            name, child_item = self.resolve(child)
            if name == "texts" and child_item.get("text", "").strip():
                texts.append(_clean(child_item["text"]))
        return Block("figure_text", "\n".join(texts), number) if texts else None
