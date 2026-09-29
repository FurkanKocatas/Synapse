"""Docling over the corpus's born-digital PDFs (docs/benchmarks/parsing.md).

    python eval/parsing/run.py [--batch PAGES] [--threads N] [--tables fast] [--backend pdfium]
                               [--out DIR] [DOC ...]

Runs in the Docling environment of eval/parsing/README.md, not in the backend's. Each
document is converted ``--batch`` pages at a time (0: whole documents), layout model and
TableFormer (``--tables``, accurate by default), OCR off (scanned pages are OCR'd by
knowledge/ocr.py). ``--backend`` picks what reads the PDF's text: Docling's own docling-parse
(the default) or PDFium, which the light parser uses.

Writes eval/parsing/work/<doc>.json (or into ``--out``), the batches as ``{"batches":
[DoclingDocument, ...]}`` in page order, and a line per document in runs.jsonl beside it:
pages, seconds, tables, the process's peak memory.

Batches are kept apart on purpose: a document converted with ``page_range`` keeps the file's
page numbers, but ``DoclingDocument.concatenate`` numbers the merged pages from 1 again, which
would send every citation to the wrong page. Blocks are made per batch and then joined.
"""

import argparse
import csv
import json
import resource
import time
from pathlib import Path

import pypdfium2 as pdfium
from docling.backend.docling_parse_backend import ThreadedDoclingParseDocumentBackend
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import DoclingDocument

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "eval" / "corpus"
WORK = Path(__file__).resolve().parent / "work"
BACKENDS = {
    "docling-parse": ThreadedDoclingParseDocumentBackend,
    "pdfium": PyPdfiumDocumentBackend,
}


def converter(threads: int, tables: TableFormerMode, backend: str) -> DocumentConverter:
    options = PdfPipelineOptions(do_ocr=False, do_table_structure=True)
    options.table_structure_options.mode = tables
    options.accelerator_options = AcceleratorOptions(num_threads=threads, device="cpu")
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=options, backend=BACKENDS[backend])
        }
    )


def convert(engine: DocumentConverter, path: Path, pages: int, batch: int) -> list[DoclingDocument]:
    if batch <= 0 or pages <= batch:
        return [engine.convert(path).document]
    return [
        engine.convert(path, page_range=(start, min(pages, start + batch - 1))).document
        for start in range(1, pages + 1, batch)
    ]


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("--batch", type=int, default=0)
    options.add_argument("--threads", type=int, default=4)
    options.add_argument("--tables", choices=["accurate", "fast"], default="accurate")
    options.add_argument("--backend", choices=sorted(BACKENDS), default="docling-parse")
    options.add_argument("--out", type=Path, default=WORK)
    options.add_argument("docs", nargs="*")
    args = options.parse_args()
    with (CORPUS / "manifest.csv").open(encoding="utf-8") as handle:
        rows = [
            r
            for r in csv.DictReader(handle)
            if r["format"] == "PDF"
            and r["is_scanned"] == "no"
            and (not args.docs or r["id"] in args.docs)
        ]
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    engine = converter(args.threads, TableFormerMode(args.tables), args.backend)
    for row in rows:
        path = CORPUS / "files" / f"{row['id']}.pdf"
        pdf = pdfium.PdfDocument(path)
        pages = len(pdf)
        pdf.close()
        started = time.perf_counter()
        batches = convert(engine, path, pages, args.batch)
        seconds = time.perf_counter() - started
        (out / f"{row['id']}.json").write_text(
            json.dumps({"batches": [b.export_to_dict() for b in batches]}, ensure_ascii=False),
            encoding="utf-8",
        )
        record = {
            "doc": row["id"],
            "pages": pages,
            "seconds": round(seconds, 1),
            "tables": sum(len(b.tables) for b in batches),
            "batch": args.batch,
            "tables_mode": args.tables,
            "backend": args.backend,
            "peak_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
        }
        with (out / "runs.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
