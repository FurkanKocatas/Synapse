# PDF parsing: the light parser against Docling

Status: **decided**, 2026-09-29: the light parser stays, Docling is not adopted for v1 ("Decision" below). Every born-digital PDF of the corpus has been through both parsers on the reference hardware.

Method and scripts: [eval/parsing/](../../eval/parsing/README.md). Requirement: [phase 4](../plan/phase-4.md), step 4 ("Docling, with and without its layout model, against the light adapter"); [ADR 0010](../adr/0010-rag-pipeline.md), ingestion rule 2 (Docling behind the `Parser` port) and rule 7 (never split a table row).

## Method in one paragraph

The 60 PDFs of the corpus that are not scans, 4,340 pages (municipal 22, legal 21, health 17), go through the light parser (PDFium's text layer, [parsing.py](../../backend/src/synapse/knowledge/parsing.py)) and through Docling 2.130 with its layout model (Heron) and TableFormer in accurate mode, OCR off. Both parsers' blocks go through the same chunker. Completeness is word and identifier recall against the text layer, per document; only the 4,077 pages that pass the page quality check count (the other 263 go to OCR whatever the parser; their text layer is often a font with a broken character map, "NRQWURO" for "kontrol", in both parsers). Page headers and footers are left out of the reference, since both parsers drop them on purpose. Table structure has no automatic reference and is checked by eye on rendered pages.

## Hardware and timing

AMD Ryzen 5 6600H (6 cores), 16 GB, Linux, CPU only, Docling on 4 threads, nothing else heavy running. Whole documents, one process for the corpus.

- **Docling: 1.75 s per page** on average (7,603 s for 4,340 pages). A least-squares fit over the documents (R² 0.98) gives about **0.8 s per page plus 35 ms per table cell**: pages without tables take 0.8 s, table-heavy strategic plans 4.5 s (doc-027: 208 tables on 161 pages). 1,000 pages take about half an hour.
- **The light parser: about 0.01 s per page.**
- Memory: see "Cost" below.

## Completeness and structure

| Strategy | Word recall | Identifier recall | Extra words | Pages on the text layer | Tables | Headings | Chunks (of them tables) | Chunk tokens p50/p90 |
|---|---|---|---|---|---|---|---|---|
| light parser | **0.9984** | **0.9986** | 1.63% | all | 0 | 541 | 7,643 (0) | 292/348 |
| Docling | 0.9904 | 0.9833 | 1.46% | none | 1,827 | 8,452 | 9,928 (2,614) | 212/343 |
| Docling + missed lines | 0.9956 | 0.9881 | 1.51% | none | 1,827 | 8,452 | 10,017 (2,621) | 210/343 |
| Docling, text layer below 0.99 | 0.9981 | 0.9941 | 1.04% | 525 (12.9%) | 1,351 | 8,035 | 9,444 (1,933) | 225/344 |
| Docling, text layer below 0.97 | 0.9978 | 0.9914 | 1.11% | 297 (7.3%) | 1,527 | 8,228 | 9,657 (2,267) | 221/343 |
| Docling, text layer below 0.90 | 0.9941 | 0.9852 | 1.39% | 80 (2.0%) | 1,773 | 8,409 | 9,880 (2,555) | 214/343 |
| both: missed lines, text layer below 0.90 | 0.9964 | 0.9887 | 1.43% | 80 (2.0%) | 1,773 | 8,409 | 9,947 (2,562) | 213/343 |

"Missed lines": after a page's blocks, the text-layer lines of which at least half the words Docling has on neither that page nor the one before. "Text layer below T": the light parser's blocks for a page where Docling keeps less than T of its words. The light parser's loss (1,670 of 1,015,124 words) is its running-line removal, by design: signature blocks and running titles repeated on every page ("Divan Kâtibi", "Revizyon No", "2025 Performans Programı") are kept where they first appear.

**What Docling adds.** Structure the light parser does not have:

- **Tables as cells.** 1,894 tables on 1,321 of the 4,340 pages (30%); 1,827 of them on pages that pass the quality check. The light parser reads a table as lines of text, so the chunker cannot repeat a table's header over its row groups or keep a row whole.
- **Headings from the page layout.** Docling finds 8,452 headings where the text rules find 541, so heading paths (the citation context and the chunk boundaries) exist for most documents instead of only for legislation.

**Tables checked by eye:** nine rendered pages with 13 tables, three chosen as hard cases (a strategic plan's indicator table, a four-table page, a budget page) and six at random with a fixed seed. Twelve tables have the right rows, columns and header: amendment lists with cells over several lines and a cell spanning two rows (21 rows by 3, 23 by 3), signature blocks, a table of contents, a key-value header box. One merges two header rows into one (doc-025, page 63). One page's header box loses its top row (the logo and the council's name) to a separate text block, without losing words.

**What Docling gets wrong**

- **It loses cells of complex tables.** Its log says so ("n of m pdf cells matched neither a row nor a column band of the grid and were dropped"). Most of its word loss is there: doc-027 keeps 0.956 of its words, doc-021 0.957; documents without complex tables keep more than 0.99.
- **It joins identifiers broken at a line end, dropping the hyphen.** "12/7/2013-" at the end of a line and "6495/73 md.)" on the next become "12/7/20136495/73"; "E-41234558-110.99-" and "10508797" become "E-41234558-110.9910508797". Of the 688 identifiers Docling "lost", 451 are there in its text but glued like this or split by other punctuation, 163 are artefacts of the text layer (table-of-contents dot leaders, footnote marks), and 74 (0.18% of 41,176) are really missing, most of them chart axis labels. An identifier merged with its neighbour is not found by exact lookup, so this would need repair before Docling could be used.

**What the comparison found in the light parser.** It put a space into the same broken identifiers ("12/7/2013- 6495/73"), which breaks exact lookup just the same. The corpus has 95 such line ends, all with a number before the hyphen and a digit after it; every one read was a single identifier or range ("08.10.2024-24/196", "(2024-2026)", "E-81912396-105.04-2026.106304.1"). Fixed: such lines are now joined keeping the hyphen ([headings.py](../../backend/src/synapse/knowledge/headings.py)); a hyphen after a number before a letter ("31- Bürolarda") stays apart.

## Docling's other PDF backend

Docling reads a PDF's text with its own docling-parse by default; it can use PDFium instead, which the light parser uses. On the five documents where Docling lost most (doc-021, doc-024, doc-027, doc-083, doc-087; 513 pages, 435 past the quality check), one process each way:

| Backend | Word recall | Identifier recall | Extra words | Seconds | Peak memory |
|---|---|---|---|---|---|
| docling-parse (default) | 0.9591 | **0.9894** | 2.43% | 1,494 | see "Cost" |
| PDFium | 0.9695 | 0.9075 | 3.69% | 1,465 | 3.8 GB |

PDFium keeps more words and needs less memory, but it writes spaces around punctuation inside the text ("01.04 . 2024 ile 31.03 . 2025", "Sayın , Meclis"), which breaks one identifier in ten. Not usable for this corpus.

## Cost

- **Memory.** One process converting whole documents grew to 5.2 GB and, by the end of the corpus, 8.8 GB. A fresh process per document, and converting a few pages at a time (run.py `--batch`):

  | Document | Pages at a time | Seconds | Peak memory |
  |---|---|---|---|
  | doc-087 (88 pages, 23 tables) | all | 101.9 | 6.4 GB |
  | doc-087 | 10 | 105.3 | 4.0 GB |
  | doc-079 (516 pages, 60 tables) | all | 586.9 | 4.1 GB |
  | doc-079 | 20 | 606.7 | 2.5 GB |

  Memory follows a document's content more than its length (the short one needs more), batches cut the peak by about 38% for 3% more time, and the models alone keep it above 2 GB. On the 16 GB tier that is the size of the OCR worker's whole limit (2.5 GB), next to the database and the language model.
- **Image size.** PyTorch (CPU) 0.73 GB and Docling's other dependencies make a 1.5 GB environment; the models are 0.37 GB (layout 164 MB, TableFormer accurate 203 MB). The app image today is 1.26 GB.
- **Licences.** The models: layout model Apache-2.0, TableFormer CDLA-Permissive-2.0, which ADR 0016 does not list and so needs a review in `docs/licences.md` before use (it is permissive: use and redistribution allowed, results unrestricted). The licence gate on Docling's 102 packages rejects four, all permissive with an unusual spelling or part: `regex` (Apache-2.0 AND CNRI-Python), `torch` (includes BSL-1.0), `torchvision` ("BSD"), `transformers` ("Apache 2.0 License").

## Decision

**The light parser stays; Docling is not adopted for v1** (2026-09-29, Furkan asked for the option the measurements favour). The parse-level numbers show what Docling adds (tables and headings) and what it costs (0.8 to 4.5 s per page, 2.5 to 6.4 GB of memory, 1.9 GB of image, a fallback to protect recall). Two checks on the golden set ([eval/retrieval/](../../eval/retrieval/README.md), 191 answerable questions, chunks with the document context in front) found no gain to pay for it:

- **Retrieval**, BM25: light parser Hit@1 0.65, Hit@10 0.95, MRR 0.757; Docling with the text layer below 0.99, 0.63, 0.93, 0.737; on table questions 0.72 and 0.98 against 0.70 and 0.98.
- **Whether a chunk can answer by itself**: for each question, the chunk on its evidence page that holds the answer, and the share of the question's words (its column and row names, for a table) in that chunk. Tables: 0.806 with the light parser, 0.811 with Docling; factual 0.787 against 0.767, identifier 0.771 against 0.787. Docling has no chunk with the answer for three questions (identifiers it glued). In this corpus a table's text layer comes row by row, and its header usually falls in the same chunk.

The golden set was written from the light parser's text, which may favour it a little; the second check depends less on that. What would change the decision: a customer corpus whose golden set shows table questions failing for want of structure (tables over many pages, header rows far from the values). The benchmark ([eval/parsing/](../../eval/parsing/README.md)) and the Docling chunk variant of the retrieval benchmark stay, to measure it again then; if adopted, it runs as its own worker image with a memory limit, converting ten pages at a time, identifiers broken at a line end repaired from the text layer, its licences reviewed first.

## Next steps

1. When the dense retriever is chosen (step 6), run the Docling chunk variant through it too; the decision above rests on lexical retrieval and on chunk contents.
2. Measure again on the first customer corpus with complex tables.
