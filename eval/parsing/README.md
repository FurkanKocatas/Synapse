# Parser benchmark

Compares the light parser ([parsing.py](../../backend/src/synapse/knowledge/parsing.py), the PDF text layer) with [Docling](https://github.com/docling-project/docling) on the corpus's born-digital PDFs. The results and the decision they led to are in [docs/benchmarks/parsing.md](../../docs/benchmarks/parsing.md).

## Method

- Every PDF of the [corpus](../corpus/README.md) that is not a scan: 60 documents.
- Docling with its layout model (Heron) and TableFormer in accurate mode, OCR off (scanned pages go to [ocr.py](../../backend/src/synapse/knowledge/ocr.py)), on the CPU with 4 threads.
- [docling_blocks.py](docling_blocks.py) turns Docling's output into Synapse blocks ([structure.py](../../backend/src/synapse/knowledge/structure.py)); [compare.py](compare.py) puts both parsers' blocks through the same chunker.
- Completeness: word recall against the text layer, as multisets per document. Page headers, footers and numbers are left out of the reference, since both parsers drop them on purpose.
- Structure is not scored automatically, as there is no ground truth for table cells. Pages are rendered and checked by eye; the benchmark lists which.

## Running it

```bash
uv sync --project eval/parsing                                          # Docling and CPU PyTorch, about 1.5 GB
uv run --project eval/parsing python eval/parsing/run.py [--batch PAGES] [DOC ...]
uv run --directory backend python ../eval/parsing/compare.py
```

The Docling environment is separate from the backend's and locked in [uv.lock](uv.lock). Its models (docling-project/docling-layout-heron, Apache-2.0; docling-project/docling-models, CDLA-Permissive-2.0) are downloaded from Hugging Face on the first run. `eval/parsing/work/` is git-ignored; it holds Docling's output for corpus documents.

`--batch` converts a document that many pages at a time, which bounds memory. Page numbers stay those of the file: the batches are stored apart, since Docling's `concatenate` numbers merged pages from 1 again.

## Limits

- The reference is the text layer, so recall says what a parser loses, not whether it reads a page in the right order. The text layer of a two-column page or a table is in typesetting order.
- Timings and memory are from one machine, a Ryzen 5 6600H with 16 GB (the reference hardware), with nothing else heavy running.
