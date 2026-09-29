"""The light parser against Docling on the corpus's born-digital PDFs (docs/benchmarks/parsing.md).

    uv run --directory backend python ../eval/parsing/compare.py [--work DIR] [--worst N]

Reads run.py's output in eval/parsing/work/ (or ``--work``). Every strategy's blocks go
through the same chunker (knowledge/chunking.py).

Recall is measured against the text layer, as multisets per document: per document, since
Docling joins a paragraph that runs over a page break into one item on its first page. Only
pages whose text layer passes the page quality check count, for every strategy: the others go
to OCR whatever the parser, and their text layer (often a font with a broken character map,
"NRQWURO" for "kontrol") is no reference. Page headers, footers and numbers that Docling marks
are left out of the reference, since both parsers drop them on purpose (ADR 0010, ingestion
rule 5).

- ``words``: share of the reference's words a strategy's blocks contain.
- ``ids``: the same for identifiers, tokens of at least 4 characters of which at least half
  the letters and digits are digits: dates, decision and law numbers, amounts, parcels. Losing
  one of these hurts search and answers most. Apostrophes, quotes and dashes are normalised on
  both sides, as search normalises them too: Docling writes some of them differently from the
  text layer ("5.000'in", "529-539").
- ``extra``: words beyond the reference's count (a strategy's duplicates), as a share of it.

Strategies:

- ``light``: the text layer's blocks (knowledge/parsing.py); PDF tables are plain lines.
- ``docling``: Docling's blocks (docling_blocks.py); tables as rows of cells.
- ``supplement``: Docling's blocks and, after a page's last block, the text-layer lines of that
  page of which at least half the words Docling has on neither that page nor the one before.
- ``fallback T``: Docling's blocks, but the text layer's for a page where Docling keeps less
  than T of the page's words (counting what it carried over from the page before).
"""

import argparse
import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

from docling_blocks import blocks_from_run
from synapse.knowledge.chunking import chunk
from synapse.knowledge.filetypes import MediaType
from synapse.knowledge.parsing import LightParser, Parsed, without_running_lines
from synapse.knowledge.structure import Block, table_text
from synapse.knowledge.turkish import lower

HERE = Path(__file__).resolve().parent
WORK = HERE / "work"
FILES = HERE.parent / "corpus" / "files"
WORD = re.compile(r"\w+")
EDGE_PUNCTUATION = ".,;:()[]\"'" + chr(0x2026)
MIN_IDENTIFIER = 4
# Typographic apostrophes, quotes and dashes as their plain forms. Written as code points: the
# repository forbids the dashes themselves in text.
PLAIN = str.maketrans(
    {chr(c): "'" for c in (0x2018, 0x2019, 0x02BC)}
    | {chr(c): '"' for c in (0x201C, 0x201D)}
    | {chr(c): "-" for c in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2212)}
)
MISSED_SHARE = 0.5
THRESHOLDS = (0.99, 0.97, 0.95, 0.90)
FURNITURE = {"page_header", "page_footer"}


def words(text: str) -> Counter[str]:
    return Counter(WORD.findall(lower(text)))


def identifiers(text: str) -> Counter[str]:
    found = Counter[str]()
    for raw in text.translate(PLAIN).split():
        token = raw.strip(EDGE_PUNCTUATION + "-")
        alnum = [ch for ch in token if ch.isalnum()]
        digits = sum(ch.isdigit() for ch in alnum)
        if len(token) >= MIN_IDENTIFIER and digits and 2 * digits >= len(alnum):
            found[token] += 1
    return found


def block_text(block: Block) -> str:
    return table_text(block.table) if block.table is not None else block.text


def furniture(saved: dict[str, Any]) -> dict[int, str]:
    """The text of what Docling marks as page headers and footers, per page."""
    pages: dict[int, list[str]] = {}
    for doc in saved["batches"]:
        for item in doc["texts"]:
            if item["label"] in FURNITURE or item.get("content_layer") == "furniture":
                for place in item.get("prov", []):
                    pages.setdefault(place["page_no"], []).append(item["text"])
    return {page: "\n".join(texts) for page, texts in pages.items()}


@dataclass
class Document:
    name: str
    pages: int
    parsed: Parsed
    # The page texts without running lines, as the light parser makes its blocks from them.
    cleaned: list[str]
    docling: list[Block]
    furniture: dict[int, str]

    def wanted(self, number: int) -> Counter[str]:
        return words(self.parsed.pages[number - 1].text) - words(self.furniture.get(number, ""))

    @cached_property
    def usable(self) -> set[int]:
        """Pages whose text layer is kept; the others are OCR'd whatever the parser."""
        return {page.number for page in self.parsed.pages if not page.needs_ocr}

    def reference(self) -> tuple[Counter[str], Counter[str]]:
        want, want_ids = Counter[str](), Counter[str]()
        for page in self.parsed.pages:
            if page.number in self.usable:
                marked = self.furniture.get(page.number, "")
                want += self.wanted(page.number)
                want_ids += identifiers(page.text) - identifiers(marked)
        return want, want_ids

    def light(self) -> list[Block]:
        return [block for page in self.parsed.pages for block in page.blocks]

    def by_page(self) -> dict[int, list[Block]]:
        pages: dict[int, list[Block]] = {}
        for block in self.docling:
            pages.setdefault(block.page, []).append(block)
        return pages

    def blocks(
        self, *, threshold: float = 0.0, supplement: bool = False
    ) -> tuple[list[Block], int]:
        """Docling's blocks with the text layer's for pages below ``threshold`` and, with
        ``supplement``, the lines Docling missed; and how many pages fell back."""
        by_page = self.by_page()
        have = {n: words("\n".join(block_text(b) for b in blocks)) for n, blocks in by_page.items()}
        out: list[Block] = []
        fell_back = 0
        usable = self.usable
        for page, text in zip(self.parsed.pages, self.cleaned, strict=True):
            if page.number not in usable:
                continue
            near = have.get(page.number, Counter()) + have.get(page.number - 1, Counter())
            want = self.wanted(page.number)
            total = sum(want.values())
            if total and sum((want & near).values()) / total < threshold:
                out += page.blocks
                fell_back += 1
                continue
            out += by_page.get(page.number, [])
            if supplement:
                out += self._missed(page.number, text, near)
        return out, fell_back

    def _missed(self, number: int, text: str, near: Counter[str]) -> list[Block]:
        available = Counter(near)
        marked = words(self.furniture.get(number, ""))
        missed = []
        for line in text.split("\n"):
            line_words = [w for w in WORD.findall(lower(line)) if not marked[w]]
            absent = [w for w in line_words if available[w] <= 0]
            available.subtract(line_words)
            if line_words and len(absent) >= MISSED_SHARE * len(line_words):
                missed.append(" ".join(line.split()))
        return [Block("paragraph", " ".join(missed), number)] if missed else []


def load(work: Path, only: set[str] | None = None) -> tuple[list[Document], list[dict[str, Any]]]:
    runs = [json.loads(line) for line in (work / "runs.jsonl").read_text().splitlines()]
    latest = {run["doc"]: run for run in runs if only is None or run["doc"] in only}
    documents = []
    for name, run in sorted(latest.items()):
        saved = json.loads((work / f"{name}.json").read_text(encoding="utf-8"))
        parsed = LightParser().parse(FILES / f"{name}.pdf", MediaType.PDF)
        cleaned = without_running_lines([page.text for page in parsed.pages])
        docling = blocks_from_run(saved)
        documents.append(Document(name, run["pages"], parsed, cleaned, docling, furniture(saved)))
    return documents, list(latest.values())


@dataclass
class Tally:
    words: int = 0
    kept: int = 0
    ids: int = 0
    ids_kept: int = 0
    extra: int = 0
    replaced: int = 0
    chunks: int = 0
    table_chunks: int = 0
    tables: int = 0
    headings: int = 0
    tokens: list[int] = field(default_factory=list)

    def add(self, doc: Document, blocks: list[Block], replaced: int) -> float:
        usable = doc.usable
        blocks = [b for b in blocks if b.page in usable]
        text = "\n".join(block_text(b) for b in blocks)
        got, got_ids = words(text), identifiers(text)
        want, want_ids = doc.reference()
        kept = sum((want & got).values())
        chunks = chunk(blocks)
        self.words += sum(want.values())
        self.kept += kept
        self.ids += sum(want_ids.values())
        self.ids_kept += sum((want_ids & got_ids).values())
        self.extra += sum((got - want).values())
        self.replaced += replaced
        self.chunks += len(chunks)
        self.table_chunks += sum(1 for c in chunks if c.kind != "text")
        self.tables += sum(1 for b in blocks if b.kind == "table")
        self.headings += sum(1 for b in blocks if b.kind == "heading")
        self.tokens += [c.tokens for c in chunks]
        return kept / max(1, sum(want.values()))


def percentile(values: Iterable[int], share: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))] if ordered else 0


def report(tallies: dict[str, Tally], pages: int) -> None:
    print(
        "strategy                   words   ids     extra  pages replaced  tables  headings"
        "  chunks (tables)  tokens p50/p90/max"
    )
    for name, t in tallies.items():
        print(
            f"  {name:<24} {t.kept / t.words:.4f}  {t.ids_kept / t.ids:.4f}"
            f"  {t.extra / t.words:5.2%}"
            f"  {t.replaced:5d} ({t.replaced / pages:5.1%})  {t.tables:6d}  {t.headings:8d}"
            f"  {t.chunks:6d} ({t.table_chunks:5d})  {percentile(t.tokens, 0.5)}/"
            f"{percentile(t.tokens, 0.9)}/{max(t.tokens, default=0)}"
        )


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("--work", type=Path, default=WORK)
    options.add_argument("--worst", type=int, default=8)
    args = options.parse_args()
    documents, runs = load(args.work)
    pages = sum(d.pages for d in documents)
    usable = sum(len(d.usable) for d in documents)
    strategies = {
        "docling": {},
        "supplement": {"supplement": True},
        **{f"fallback {t}": {"threshold": t} for t in THRESHOLDS},
        "supplement, fallback 0.9": {"supplement": True, "threshold": 0.9},
    }
    tallies = {name: Tally() for name in ("light", *strategies)}
    per_doc = []
    for doc in documents:
        tallies["light"].add(doc, doc.light(), 0)
        recalls = {
            name: tallies[name].add(doc, *doc.blocks(**settings))
            for name, settings in strategies.items()
        }
        per_doc.append((recalls["docling"], doc.name, doc.pages, recalls["supplement"]))

    seconds = sum(r["seconds"] for r in runs)
    peak = max(r["peak_mb"] for r in runs)
    print(
        f"{len(documents)} documents, {pages} pages; "
        f"Docling {seconds / pages:.2f} s/page, peak {peak} MB"
    )
    print(f"{usable} pages pass the page quality check; the rest go to OCR and are left out")
    report(tallies, usable)
    print("lowest Docling word recall (recall, document, pages, with supplement):")
    for recall, name, n, supplemented in sorted(per_doc)[: args.worst]:
        print(f"  {recall:.4f}  {name}  {n:4d}  {supplemented:.4f}")


if __name__ == "__main__":
    main()
