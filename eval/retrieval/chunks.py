"""The corpus as chunks, the way ingestion makes them, for the retrieval benchmark (README.md).

    uv run --directory backend python ../eval/retrieval/chunks.py [--parser light|docling]
                                                                  [--context]

Every corpus document the light parser reads is parsed, its pages that pass the page quality
check are cut into chunks by the product's chunker, and each chunk is written with its
document, pages and the text search indexes (``indexed_text``: heading path, then text) to
eval/retrieval/work/chunks-<parser>.jsonl. Scanned pages are left out until the corpus has been
through OCR; the golden set has no questions on them yet.

``--context`` puts a document context in front of every chunk (ADR 0010, ingestion rule 9, the
deterministic prefix; written to chunks-<parser>-context.jsonl): the name of the file as it was
published (the name it would be uploaded with, from the manifest's URL, separators as spaces)
and the document's first 30 words. Only what ingestion knows: no title written for the corpus.

``--parser docling`` takes a born-digital PDF's blocks from Docling instead (eval/parsing/,
its output must be in eval/parsing/work/), with the text layer's blocks for any page where
Docling keeps less than 0.99 of the words: the variant docs/benchmarks/parsing.md proposes to
compare.
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from synapse.knowledge.chunking import chunk, indexed_text
from synapse.knowledge.filetypes import MediaType
from synapse.knowledge.parsing import LightParser, ParseError
from synapse.knowledge.structure import Block

HERE = Path(__file__).resolve().parent
CORPUS = HERE.parent / "corpus"
WORK = HERE / "work"
MEDIA = {
    "PDF": MediaType.PDF,
    "DOCX": MediaType.DOCX,
    "XLSX": MediaType.XLSX,
    "PPTX": MediaType.PPTX,
}
FALLBACK = 0.99
OPENING_WORDS = 30
OPENING_CHUNKS = 5
SEPARATORS = re.compile(r"[_.-]+")


def file_name(url: str) -> str:
    return " ".join(SEPARATORS.sub(" ", Path(unquote(urlparse(url).path)).stem).split())


def docling_blocks(doc: str) -> list[Block] | None:
    """Docling's blocks with the text-layer fallback, or None without Docling output."""
    sys.path.insert(0, str(HERE.parent / "parsing"))
    import compare  # noqa: PLC0415  (eval/parsing, only for this variant)

    work = HERE.parent / "parsing" / "work"
    if not (work / f"{doc}.json").exists():
        return None
    documents, _ = compare.load(work, only={doc})
    blocks, _ = documents[0].blocks(threshold=FALLBACK)
    return blocks


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("--parser", choices=["light", "docling"], default="light")
    options.add_argument("--context", action="store_true")
    args = options.parse_args()
    WORK.mkdir(exist_ok=True)
    with (CORPUS / "manifest.csv").open(encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle) if row["format"] in MEDIA]
    out = WORK / f"chunks-{args.parser}{'-context' if args.context else ''}.jsonl"
    count = 0
    with out.open("w", encoding="utf-8") as handle:
        for row in rows:
            path = CORPUS / "files" / f"{row['id']}.{row['format'].lower()}"
            try:
                pages = LightParser().parse(path, MEDIA[row["format"]]).pages
            except ParseError:
                continue
            usable = {page.number for page in pages if not page.needs_ocr}
            blocks = docling_blocks(row["id"]) if args.parser == "docling" else None
            if blocks is None:
                blocks = [b for page in pages for b in page.blocks]
            blocks = [b for b in blocks if b.page in usable]
            chunks = chunk(blocks)
            prefix = ""
            if args.context and chunks:
                # From the first chunks together: a first chunk can be a lone "T.C.".
                words = " ".join(indexed_text(c) for c in chunks[:OPENING_CHUNKS]).split()
                opening = " ".join(words[:OPENING_WORDS])
                prefix = f"{file_name(row['source_url'])}\n{opening}\n"
            for c in chunks:
                record = {
                    "id": f"{row['id']}#{c.ordinal}",
                    "doc": row["id"],
                    "kind": c.kind,
                    "pages": [c.page_start, c.page_end],
                    "text": prefix + indexed_text(c),
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1
    print(f"{count} chunks in {out.relative_to(HERE.parent.parent)}")


if __name__ == "__main__":
    main()
