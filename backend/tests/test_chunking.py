"""The chunking rules of knowledge/chunking.py, as properties over generated documents."""

from itertools import pairwise

from hypothesis import given, settings
from hypothesis import strategies as st

from synapse.knowledge.chunking import (
    OPENING_CHUNKS,
    OPENING_WORDS,
    Chunk,
    ChunkingConfig,
    chunk,
    contextual_text,
    document_context,
    indexed_text,
    join_continued_tables,
)
from synapse.knowledge.structure import Block, Table, row_text

CONFIG = ChunkingConfig(target_tokens=30, max_tokens=50, soft_min_tokens=10)


def words(text: str) -> int:
    """A token counter the tests can reason about: one token per word."""
    return len(text.split())


WORD = st.sampled_from(
    [
        *("karar", "meclis", "belediye", "madde", "bütçe", "tutar", "2026/35", "kabul"),
        *("ılık", "şehir", "üçüncü", "₺2.500", "izin"),
    ]
)
SENTENCE = st.lists(WORD, min_size=1, max_size=18).map(lambda w: " ".join(w).capitalize() + ".")
PARAGRAPH = st.lists(SENTENCE, min_size=1, max_size=12).map(" ".join)
CELL = st.lists(WORD, min_size=0, max_size=4).map(" ".join)


@st.composite
def tables(draw: st.DrawFn) -> Table:
    """Rows short enough to fit a chunk with their header (long rows: their own test)."""
    width = draw(st.integers(1, 5))
    rows = draw(st.lists(st.tuples(*[CELL] * width), min_size=1, max_size=40))
    return Table(tuple(rows), draw(st.integers(0, 1)))


@st.composite
def tables_with_long_rows(draw: st.DrawFn) -> Table:
    labels = st.lists(WORD, min_size=1, max_size=3).map(" ".join)
    body = draw(st.lists(st.tuples(labels, PARAGRAPH), min_size=1, max_size=4))
    return Table((("Kalem", "Açıklama"), *body), header_rows=1)


@st.composite
def documents(draw: st.DrawFn) -> list[Block]:
    blocks: list[Block] = []
    page = 1
    for _ in range(draw(st.integers(1, 25))):
        page += draw(st.integers(0, 1))
        kind = draw(st.sampled_from(["heading", "paragraph", "paragraph", "table", "article"]))
        if kind == "heading":
            level = draw(st.integers(1, 4))
            blocks.append(Block("heading", f"Başlık {len(blocks)}", page, level=level))
        elif kind == "article":
            text = f"Madde {len(blocks)}- " + draw(PARAGRAPH)
            blocks.append(Block("paragraph", text, page, level=3, label=f"Madde {len(blocks)}"))
        elif kind == "table":
            blocks.append(Block("table", "", page, table=draw(tables())))
        else:
            blocks.append(Block("paragraph", draw(PARAGRAPH), page))
    return blocks


def run(blocks: list[Block]) -> list[Chunk]:
    return chunk(blocks, CONFIG, count=words)


@settings(max_examples=300)
@given(documents())
def test_running_text_and_headings_are_kept_whole_and_in_order(blocks: list[Block]) -> None:
    expected: list[str] = []
    pending: list[str] = []
    for b in blocks:
        if b.kind == "heading":
            pending += b.text.split()
        elif b.kind == "table":
            pending = []  # kept in the table's heading path
        else:
            expected += pending + b.text.split()
            pending = []
    expected += pending
    got = [w for c in run(blocks) if c.kind == "text" for w in c.text.split()]
    assert got == expected


@settings(max_examples=300)
@given(documents())
def test_table_rows_are_never_split_and_headers_repeat(blocks: list[Block]) -> None:
    chunks = run(blocks)
    for index, (block, _) in enumerate(join_continued_tables(blocks)):
        if block.table is None:
            continue
        header = [line for line in map(row_text, block.table.header) if line]
        rows = [line for line in map(row_text, block.table.body) if line]
        mine = [c for c in chunks if c.kind == "table" and c.blocks == (index, index)]
        seen: list[str] = []
        for c in mine:
            lines = c.text.split("\n")
            assert lines[: len(header)] == header
            seen += lines[len(header) :]
        assert seen == rows


@settings(max_examples=300)
@given(documents())
def test_no_chunk_is_over_the_limit(blocks: list[Block]) -> None:
    for c in run(blocks):
        assert c.tokens <= CONFIG.max_tokens, c


@settings(max_examples=300)
@given(tables_with_long_rows())
def test_a_row_too_long_for_a_chunk_is_split_under_its_header_and_label(table: Table) -> None:
    chunks = [c for c in run([Block("table", "", 3, table=table)]) if c.kind == "table"]
    got: list[str] = []
    for c in chunks:
        assert c.tokens <= CONFIG.max_tokens, c
        header, *body = c.text.split("\n")
        assert header == "Kalem | Açıklama"
        # Every row line has " | "; a chunk starting without one continues a long row, and
        # starts with that row's label on a line of its own.
        if " | " not in body[0]:
            assert len(body) == 2, c
            assert body[0] in {row[0] for row in table.body}, c
            body = body[1:]
        got += [w for line in body for w in line.split()]
    assert got == [w for row in table.body for w in row_text(row).split()]


@settings(max_examples=300)
@given(documents())
def test_chunks_never_cross_a_level_1_or_2_heading(blocks: list[Block]) -> None:
    joined = [b for b, _ in join_continued_tables(blocks)]
    section, sections = 0, []
    for b in joined:
        if b.level is not None and b.level <= CONFIG.hard_level:
            section += 1
        sections.append(section)
    for c in run(blocks):
        first, last = c.blocks
        # Headings may lead a chunk (a part's title over its first chapter); its body may not
        # come from two sections.
        body = {sections[i] for i in range(first, last + 1) if joined[i].kind != "heading"}
        assert len(body) <= 1, c


@settings(max_examples=200)
@given(documents())
def test_pages_and_order(blocks: list[Block]) -> None:
    chunks = run(blocks)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    for c in chunks:
        assert 1 <= c.page_start <= c.page_end
    for a, b in pairwise(chunks):
        assert a.blocks[0] <= b.blocks[0]


def test_a_large_table_gets_a_summary_naming_its_columns_and_rows() -> None:
    rows = (("Kalem", "Tutar"), *((f"Kalem {n}", f"{n}.000 TL") for n in range(30)))
    chunks = run([Block("table", "", 4, table=Table(rows, header_rows=1))])
    assert [c.kind for c in chunks][-1] == "table_summary"
    summary = chunks[-1].text
    assert summary.startswith("Tablo: 30 satır, 2 sütun.")
    assert "Sütunlar: Kalem | Tutar" in summary
    assert "Kalem 0; Kalem 1" in summary
    assert all(c.page_start == c.page_end == 4 for c in chunks)


def test_a_table_continued_on_the_next_page_is_one_table() -> None:
    header = ("Ada", "Parsel", "Alan")
    first = Table((header, ("1", "2", "300"), ("1", "3", "450")), header_rows=1)
    repeated = Table((header, ("2", "7", "120")), header_rows=1)
    bare = Table((("3", "1", "90"),))
    # Not continuations: a page is skipped; then a different header on the next page; then a
    # different width.
    distant = Table((("4", "4", "40"),))
    other_header = Table((("İl", "İlçe", "Nüfus"), ("5", "5", "50")), header_rows=1)
    narrower = Table((("a", "b"),))
    blocks = [
        Block("table", "", 5, table=first),
        Block("table", "", 6, table=repeated),
        Block("table", "", 7, table=bare),
        Block("table", "", 9, table=distant),
        Block("table", "", 10, table=other_header),
        Block("table", "", 11, table=narrower),
    ]
    joined = join_continued_tables(blocks)
    assert [(b.page, last) for b, last in joined] == [(5, 7), (9, 9), (10, 10), (11, 11)]
    table = joined[0][0].table
    assert table is not None
    assert table.rows == (
        header,
        ("1", "2", "300"),
        ("1", "3", "450"),
        ("2", "7", "120"),
        ("3", "1", "90"),
    )


def test_heading_path_follows_the_sections() -> None:
    blocks = [
        Block("heading", "BİRİNCİ KISIM Genel Hükümler", 1, level=1),
        Block("heading", "BİRİNCİ BÖLÜM Amaç", 1, level=2),
        Block("paragraph", "Madde 1- Bu Kanunun amacı belediyeyi düzenlemektir.", 1, 3, "Madde 1"),
        Block("heading", "İKİNCİ BÖLÜM Kuruluş", 2, level=2),
        Block("paragraph", "Madde 4- Belediye kurulur.", 2, 3, "Madde 4"),
    ]
    chunks = run(blocks)
    assert [c.heading_path for c in chunks] == [
        ("BİRİNCİ KISIM Genel Hükümler", "BİRİNCİ BÖLÜM Amaç", "Madde 1"),
        ("BİRİNCİ KISIM Genel Hükümler", "İKİNCİ BÖLÜM Kuruluş", "Madde 4"),
    ]
    assert [c.page_start for c in chunks] == [1, 2]


def sections(count: int, paragraph: str) -> list[Chunk]:
    """One chunk per section: a level 1 heading always starts a new one."""
    blocks = []
    for n in range(count):
        blocks += [
            Block("heading", f"BÖLÜM {n}", 1, level=1),
            Block("paragraph", paragraph.format(n=n), 1),
        ]
    return run(blocks)


def test_the_document_context_is_its_file_name_and_first_30_words() -> None:
    chunks = sections(10, "a{n} b{n} c{n} d{n} e{n} f{n} g{n} h{n}")
    name, opening = document_context("2026_16-meclis.kararı.pdf", chunks).split("\n")
    assert name == "2026 16 meclis kararı"
    first = " ".join(indexed_text(c) for c in chunks).split()
    assert opening.split() == first[:OPENING_WORDS]
    assert document_context("bos.pdf", []) == "bos"
    assert document_context("", chunks) == opening


def test_the_opening_words_come_from_the_first_five_chunks_only() -> None:
    # A few words a chunk: the first five hold fewer than 30, and the sixth is not read.
    chunks = sections(10, "a{n}")
    assert len(chunks) == 10
    opening = document_context("x.pdf", chunks).split("\n")[1].split()
    assert opening == " ".join(indexed_text(c) for c in chunks[:OPENING_CHUNKS]).split()
    assert len(opening) < OPENING_WORDS
    assert "a4" in opening
    assert "a5" not in opening


def test_the_embedded_text_is_the_context_then_the_indexed_text() -> None:
    assert contextual_text("ad\nilk sözler", ("BÖLÜM 1", "Madde 4"), "Belediye kurulur.") == (
        "ad\nilk sözler\nBÖLÜM 1\nMadde 4\nBelediye kurulur."
    )
    assert contextual_text("", (), "Metin.") == "Metin."
