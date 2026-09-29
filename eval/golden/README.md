# Golden set

Turkish questions over the [evaluation corpus](../corpus/README.md), each anchored to the page that answers it: the reference for retrieval and answer quality ([ADR 0010](../../docs/adr/0010-rag-pipeline.md), "Evaluation gates"; [phase 4](../../docs/plan/phase-4.md), step 9).

Status: **draft 1, 2026-09-29.** Checked mechanically ([check.py](check.py)); not yet reviewed by a person. Scanned documents are not covered yet (below).

## Contents

225 questions in [questions.jsonl](questions.jsonl), one JSON object per line:

| Type | Count | What it tests |
|---|---|---|
| `factual` | 65 | a fact stated in running text |
| `identifier` | 62 | a question that names an identifier or asks for one: decision, law and article numbers, dates, E./K. numbers, indicator and standard codes, amounts |
| `table` | 43 | a table cell, found by its row and column |
| `multi_document` | 21 | an answer with one part from each of two documents |
| `unanswerable` | 34 (15%) | a plausible question the corpus does not answer: another municipality, another year, an article that does not exist, a law that is not in the corpus |

Evidence comes from 86 documents: 35 municipal, 28 legal, 23 health.

```json
{"id": "g6-03", "type": "identifier",
 "question": "3194 sayılı İmar Kanunu'nda ruhsatsız ya da ruhsata aykırı olarak başlanan yapılar hangi maddede düzenlenir?",
 "answer": "Madde 32",
 "evidence": [{"doc": "doc-050", "page": 25, "quote": "Ruhsatsız veya ruhsat ve eklerine aykırı olarak başlanan yapılar: Madde 32 - ..."}]}
```

- `answer`: short, written as the source writes it. `answer_parts` (multi_document only): one part per document.
- `evidence`: document, page (the file's own page number; a DOCX is one page, an XLSX sheet is one page) and `quote`, 5 to 40 words copied from that page, containing the answer. The quote is the content anchor: page numbers can be checked against it whatever the parser.
- `also`: other pages that answer the question: where the same quote occurs (a table printed twice, a law quoted word for word in a guide), found by search, and pages that state the answer in other words, found by reading the retrieval misses (three so far). A retrieval hit on any of them counts.
- `note` (unanswerable only): why the corpus has no answer.

## How it was made

Questions were drafted with a language model from the per-page text the light parser extracts (pages that pass the page quality check only), document by document, with written rules: natural wording as a clerk, lawyer or hospital employee would type it, enough context to be unambiguous in the whole corpus (the municipality, the law, the year), a unique answer supported by the quoted page, no yes/no questions, no arithmetic, no outside knowledge, no personal names. Every unanswerable question was searched for in the corpus's text, and every page where its terms occur was read.

[check.py](check.py) verifies, against the parser's pages: every quote is on its stated page, every answer (or answer part) is in a quote, the types, ids and quote lengths, that no evidence sits on a page that goes to OCR, and the repository's dash rule. It passes with 0 failures.

```bash
uv run --directory backend python ../eval/golden/check.py
```

## Known gaps

- **Not reviewed by a person yet.** The mechanical check proves anchors, not that a question is natural or that its answer is the only right one.
- **An answer can occur elsewhere in other words.** `also` lists exact repeats of a quote only. A Board decision number, for example, can be cited in a guide and in the decision compilation. Scoring (step 9) should therefore also accept a retrieved page that holds the answer and the question's key terms, and report how often that decides a hit.
- **Scanned documents are not covered**: the questions were written from text layers. Questions on OCR'd pages come once the corpus has been through the worker, with the uncertain-identifier flags in view.
- **Legacy `.doc` files** (three) are not read by the parser and have no questions.
- Quotes keep the source's own errors (old orthography, OCR text of old court decisions, typos), since they must match the page.
