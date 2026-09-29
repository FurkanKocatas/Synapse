"""Chunks: the units search indexes and answers cite (ADR 0010, ingestion rules 7 and 9).

Rules, each covered by a property test (tests/test_chunking.py):

1. A chunk never crosses a heading at ``hard_level`` or above (levels 1 and 2 by default).
   A deeper section (an article, "3.2.") starts a new chunk once the current one holds at
   least ``soft_min_tokens``.
2. About ``target_tokens`` per chunk and never more than ``max_tokens``; running text longer
   than that is split at sentence ends, and at word boundaries if a sentence is longer still.
3. A table row is never split. A table that does not fit in one chunk becomes groups of whole
   rows, each repeating the table's header rows, plus a summary chunk that names its columns and
   rows. The one chunk allowed over ``max_tokens`` is a single row too long for it, with its
   header.
4. A table continued on the next page (same column count, no header or the same header) is
   joined first, so its rows are grouped as one table.
5. No text is lost or repeated: the running text of the chunks, in order, is the running text
   of the blocks.

Every chunk keeps its heading path and pages; the deterministic context prefix (title, type,
date, number, heading path, page) is built from them when the chunk is indexed.
"""

import math
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal

from synapse.knowledge.language import Language, language
from synapse.knowledge.structure import Block, Table, row_text
from synapse.knowledge.turkish import lower

ChunkKind = Literal["text", "table", "table_summary"]
type TokenCounter = Callable[[str], int]

# The multilingual tokenizers the embedding candidates share (XLM-R's, used by e5 and bge-m3)
# give 4.18 characters per token on the corpus's Turkish text at the median and 3.65 at the
# densest tenth of pages. Until the embedder is chosen (phase 4, step 6), 3.6 keeps the estimate
# on the safe side of the real count.
CHARS_PER_TOKEN = 3.6


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


@dataclass(frozen=True)
class ChunkingConfig:
    target_tokens: int = 350
    max_tokens: int = 512
    hard_level: int = 2
    soft_min_tokens: int = 120
    # Row labels listed in a table's summary chunk, at most.
    summary_labels: int = 40
    # The documents' language: sentence ends and the words of a table summary.
    words: Language = field(default_factory=language)

    def __post_init__(self) -> None:
        if not 0 < self.soft_min_tokens <= self.target_tokens <= self.max_tokens:
            raise ValueError("need 0 < soft_min_tokens <= target_tokens <= max_tokens")


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    kind: ChunkKind
    text: str
    heading_path: tuple[str, ...]
    page_start: int
    page_end: int
    tokens: int
    # Indices of the first and last block the chunk takes text from.
    blocks: tuple[int, int]


@dataclass
class _Draft:
    parts: list[str] = field(default_factory=list)
    tokens: int = 0
    pages: list[int] = field(default_factory=list)
    first_block: int = -1
    last_block: int = -1
    # The heading path where the chunk starts: what a citation of it should name. Sections
    # merged into it later (short articles) carry their own label in their text.
    path: tuple[str, ...] = ()

    def add(self, text: str, tokens: int, page: int, index: int, path: tuple[str, ...]) -> None:
        if not self.parts:
            self.first_block = index
            self.path = path
        self.parts.append(text)
        self.tokens += tokens
        self.pages.append(page)
        self.last_block = index


class _Builder:
    def __init__(self, config: ChunkingConfig, count: TokenCounter) -> None:
        self.config = config
        self.count = count
        self.chunks: list[Chunk] = []
        self.path: list[tuple[int, str]] = []
        self.draft = _Draft()

    def heading_path(self) -> tuple[str, ...]:
        return tuple(label for _, label in self.path)

    def emit(
        self,
        kind: ChunkKind,
        text: str,
        pages: Sequence[int],
        blocks: tuple[int, int],
        path: tuple[str, ...] | None = None,
    ) -> None:
        self.chunks.append(
            Chunk(
                ordinal=len(self.chunks),
                kind=kind,
                text=text,
                heading_path=self.heading_path() if path is None else path,
                page_start=min(pages),
                page_end=max(pages),
                tokens=self.count(text),
                blocks=blocks,
            )
        )

    def flush(self) -> None:
        draft = self.draft
        if draft.parts:
            span = (draft.first_block, draft.last_block)
            self.emit("text", "\n".join(draft.parts), draft.pages, span, draft.path)
        self.draft = _Draft()

    def open_section(self, level: int, label: str) -> None:
        if level <= self.config.hard_level or self.draft.tokens >= self.config.soft_min_tokens:
            self.flush()
        while self.path and self.path[-1][0] >= level:
            self.path.pop()
        self.path.append((level, label))

    def text(self, text: str, page: int, index: int) -> None:
        pieces = split_text(text, self.config.max_tokens, self.count, self.config.words)
        for piece in pieces:
            tokens = self.count(piece)
            if self.draft.parts and self.draft.tokens + tokens > self.config.target_tokens:
                self.flush()
            self.draft.add(piece, tokens, page, index, self.heading_path())

    def table(self, table: Table, page_start: int, page_end: int, index: int) -> None:
        self.flush()
        pages = (page_start, page_end)
        header = [line for line in map(row_text, table.header) if line]
        rows = [line for line in map(row_text, table.body) if line]
        whole = "\n".join(header + rows)
        if not whole:
            return
        if self.count(whole) <= self.config.max_tokens:
            self.emit("table", whole, pages, (index, index))
            return
        for group in _row_groups(header, rows, self.config.target_tokens, self.count):
            self.emit("table", "\n".join(header + group), pages, (index, index))
        self.emit("table_summary", self._summary(table, header), pages, (index, index))

    def _summary(self, table: Table, header: list[str]) -> str:
        words = self.config.words.table_summary
        labels = [row[0] for row in table.body if row and row[0]]
        width = max(map(len, table.rows))
        lines = [f"{words.table}: {len(table.body)} {words.rows}, {width} {words.columns}."]
        if header:
            lines.append(f"{words.column_names}: " + " / ".join(header))
        if labels:
            shown = "; ".join(labels[: self.config.summary_labels])
            lines.append(f"{words.row_labels}: {shown}")
        text = "\n".join(lines)
        # A summary is a pointer to the rows, so it is cut rather than split.
        while self.count(text) > self.config.max_tokens:
            text = text[: int(len(text) * 0.9)].rsplit(" ", 1)[0]
        return text


def chunk(
    blocks: Sequence[Block],
    config: ChunkingConfig | None = None,
    count: TokenCounter = estimate_tokens,
) -> list[Chunk]:
    builder = _Builder(config or ChunkingConfig(), count)
    merged = join_continued_tables(blocks)
    for index, (block, last_page) in enumerate(merged):
        if block.level is not None:
            builder.open_section(block.level, block.label or block.text)
        if block.kind == "heading":
            continue
        if block.table is not None:
            builder.table(block.table, block.page, last_page, index)
        elif block.text.strip():
            builder.text(block.text, block.page, index)
    builder.flush()
    return builder.chunks


def join_continued_tables(blocks: Sequence[Block]) -> list[tuple[Block, int]]:
    """Blocks with continued tables joined, each with the last page it covers.

    A table continues the one before it when it starts on the next page, has as many columns,
    and has no header rows or the same ones (repeated headers are dropped).
    """
    joined: list[tuple[Block, int]] = []
    for block in blocks:
        if joined:
            previous, last_page = joined[-1]
            if (
                previous.table is not None
                and block.table is not None
                and block.page == last_page + 1
                and _width(block.table) == _width(previous.table)
                and (block.table.header_rows == 0 or block.table.header == previous.table.header)
            ):
                table = Table(previous.table.rows + block.table.body, previous.table.header_rows)
                joined[-1] = (replace(previous, table=table), block.page)
                continue
        joined.append((block, block.page))
    return joined


def _width(table: Table) -> int:
    return max(map(len, table.rows), default=0)


def _row_groups(
    header: list[str], rows: list[str], target: int, count: TokenCounter
) -> Iterator[list[str]]:
    base = count("\n".join(header)) if header else 0
    group: list[str] = []
    tokens = base
    for row in rows:
        row_tokens = count(row)
        if group and tokens + row_tokens > target:
            yield group
            group, tokens = [], base
        group.append(row)
        tokens += row_tokens
    if group:
        yield group


# A sentence ends at a full stop, question or exclamation mark followed by a capital or digit.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[“‘]?(?:[^\W\d_]|\d))")


def split_text(
    text: str, max_tokens: int, count: TokenCounter, words: Language | None = None
) -> list[str]:
    """``text`` as pieces of at most ``max_tokens``: whole if it fits, else at sentence ends,
    else at word boundaries."""
    if count(text) <= max_tokens:
        return [text]
    abbreviations = (words or language()).abbreviations
    pieces: list[str] = []
    current = ""
    for sentence in _sentences(text, abbreviations):
        for part in _fit_words(sentence, max_tokens, count):
            candidate = f"{current} {part}" if current else part
            if current and count(candidate) > max_tokens:
                pieces.append(current)
                current = part
            else:
                current = candidate
    if current:
        pieces.append(current)
    return pieces


def _sentences(text: str, abbreviations: frozenset[str]) -> list[str]:
    sentences: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        following = text[match.end() : match.end() + 2].lstrip("\"'([“‘")[:1]
        if not (following.isupper() or following.isdigit()):
            continue
        before = lower(text[start : match.start()].rsplit(" ", 1)[-1].rstrip("."))
        # An abbreviation or a single letter ("A.", an initial) does not end a sentence.
        if before in abbreviations or (len(before) == 1 and before.isalpha()):
            continue
        sentences.append(text[start : match.start()])
        start = match.end()
    sentences.append(text[start:])
    return [s for s in sentences if s]


def _fit_words(sentence: str, max_tokens: int, count: TokenCounter) -> list[str]:
    if count(sentence) <= max_tokens:
        return [sentence]
    parts: list[str] = []
    current = ""
    for word in sentence.split(" "):
        candidate = f"{current} {word}" if current else word
        if current and count(candidate) > max_tokens:
            parts.append(current)
            current = word
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts
