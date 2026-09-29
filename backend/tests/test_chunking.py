"""The chunking rules of knowledge/chunking.py, as properties over generated documents."""

from itertools import pairwise

from hypothesis import given, settings
from hypothesis import strategies as st

from synapse.knowledge.chunking import Chunk, ChunkingConfig, chunk, join_continued_tables
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
    width = draw(st.integers(1, 5))
    rows = draw(st.lists(st.tuples(*[CELL] * width), min_size=1, max_size=40))
    return Table(tuple(rows), draw(st.integers(0, min(2, len(rows)))))


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
def test_running_text_is_kept_whole_and_in_order(blocks: list[Block]) -> None:
    expected = [w for b in blocks if b.kind == "paragraph" for w in b.text.split()]
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
def test_no_chunk_is_over_the_limit_but_a_single_long_row(blocks: list[Block]) -> None:
    for c in run(blocks):
        if c.tokens > CONFIG.max_tokens:
            assert c.kind == "table"
            header_lines = _header_lines(blocks, c)
            assert len(c.text.split("\n")) - header_lines == 1, c


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
        assert sections[first] == sections[last], c


@settings(max_examples=200)
@given(documents())
def test_pages_and_order(blocks: list[Block]) -> None:
    chunks = run(blocks)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    for c in chunks:
        assert 1 <= c.page_start <= c.page_end
    for a, b in pairwise(chunks):
        assert a.blocks[0] <= b.blocks[0]


def _header_lines(blocks: list[Block], c: Chunk) -> int:
    block, _ = join_continued_tables(blocks)[c.blocks[0]]
    assert block.table is not None
    return len([line for line in map(row_text, block.table.header) if line])


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
