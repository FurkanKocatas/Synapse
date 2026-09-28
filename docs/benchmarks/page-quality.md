# Page quality check: calibration on the evaluation corpus

Date: 2026-09-28. Code: [quality.py](../../backend/src/synapse/knowledge/quality.py). Scripts: [eval/quality/](../../eval/quality/). Requirement: [ADR 0010](../adr/0010-rag-pipeline.md), ingestion rule 3.

## Question

Which PDF pages have a text layer that is present but unusable, so the page must go to OCR? The case that matters in practice: scanners that write their own OCR into the PDF. In the corpus, doc-004 (a municipal regulation draft, 53 pages) reads like this:

> Bc,ledi.ve encümeni ile ilgili giirer leri ... kamu kuruııılarıııa giden evraklarıı,ı göndcrilmesi

A check that only asks "is there text?" passes every one of its pages.

## Method

Two signals per page:

1. **Character score:** mean log2-probability per letter of the page's lower-case words under a character trigram model. Lower-case only, because names, places and acronyms are capitalized and look foreign to any model. The model is built from the corpus's born-digital PDFs, which include English references.
2. **Artefact share:** share of words with commas, semicolons, `|` or `\` between letters, a lower-case "ıı", or a case change inside a long word. Units (`mg/kg`), abbreviations (`T.C.`), formulas (`HbA1c`), suffixes after apostrophes (`KHK'nin`), hyphenated parts (`SARS-CoV-2`) and Roman numerals are not artefacts.

**Two-fold cross-validation:** the 60 born-digital PDFs are split in two; a model built from one half scores the other, so no clean page is judged by a model that saw it. doc-004 is scored by both models.

## Results

Thresholds were chosen by a grid over the character threshold (-3.3 to -4.2) and the artefact threshold (0.03 to 0.08):

| Character threshold | Artefact threshold | Clean pages flagged (of 4,312, doc-083 excluded) | doc-004 pages caught (of 53) |
|---|---|---|---|
| -3.3 | 0.05 | 79 | 28 |
| -3.9 | 0.05 | 46 | 28 |
| -4.2 | 0.05 | 41 | 28 |
| **-4.2** | **0.03** | **76 (1.8%)** | **37** |
| -4.2 | 0.08 | 34 | 18 |

Chosen: **-4.2 and 0.03**.

- In doc-004, every page is caught by the artefact rule; the character threshold only adds false positives, so it is set low, where it catches only text that looks like no language at all.
- The 16 doc-004 pages left unflagged have mild errors ("tarafindan", "Kültiir") and are readable.
- **doc-083 is a real find:** a born-digital PDF whose font encoding is broken, so its text layer reads "$PHULND%LUOHúLN'HYOHWOHUL". All 28 of its broken pages are flagged, and they need OCR as much as a scan does. That is why it is excluded from the false-positive count.
- The remaining false positives are mostly reference lists in English and pages that are tables of codes.

## Consequences for the pipeline

- A false positive costs OCR time and must never cost quality: after OCR (step 4), the page keeps whichever text scores better, so a good text layer is never replaced by worse OCR.
- The score and reason are stored per page (`document_pages.quality_issue`, `char_score`, `artefacts`) for the administrators' OCR summary.
- The model file is 9,632 trigram counts (about 100 KB) built from the corpus; it holds no text. Rebuilding: `uv run --directory backend python ../eval/quality/build_char_model.py`. Re-running the calibration: `.../calibrate.py`.
- To revisit with a bigger corpus: the thresholds, and whether short pages (under 80 letters in lower-case words) should be judged at all.
