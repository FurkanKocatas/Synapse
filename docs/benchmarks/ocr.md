# OCR engines for Turkish: benchmark

Status: **in progress**, 2026-09-28. No engine is chosen yet. Method and scripts: [eval/ocr/](../../eval/ocr/README.md). Requirement: [ADR 0010](../adr/0010-rag-pipeline.md), ingestion rule 4 ("other engines only after they pass the Turkish character benchmark").

## Method in one paragraph

112 born-digital pages from 56 corpus documents (municipal 42, legal 38, health 32) are rendered to images in three conditions: `clean` 300 dpi; `scan` 200 dpi grey, tilted, blurred, noisy (the corpus's real municipal scans are 200 dpi); `poor` 150 dpi black and white, speckled, low-quality JPEG. The OCR output is compared with the page's own text layer. Metrics: character error rate; order-independent word F1; recall of words with Turkish letters (`tr_recall`); recall of identifiers (`id_recall`: tokens of at least 4 characters, at least half digits: dates, decision and law numbers, amounts). Three real scanned pages are transcribed by hand ([eval/ocr/real/](../../eval/ocr/real/)) to check that the simulation holds. The target for identifiers is the ADR 0010 bar for exact-identifier retrieval: an OCR engine that loses one identifier in ten cannot reach it.

## Results so far (Tesseract 5.5.0, LSTM, page segmentation 3)

`scan` condition, mean over pages (worst 10% of pages in brackets):

| Engine | Word F1 | Turkish-letter words | Identifiers | Seconds per page (one thread, Docker on the work laptop) |
|---|---|---|---|---|
| Tesseract `tessdata_fast` tur (identical to Debian's package) | 0.956 | 0.975 | 0.884 (0.23) | 0.9 |
| Tesseract `tessdata_best` tur | 0.960 | 0.977 | 0.908 (0.36) | 2.3 |
| Tesseract `tessdata_best` tur+eng | 0.959 | 0.967 | 0.923 (0.43) | 2.5 |

`clean` is about one point better on every column, `poor` 3 to 8 points worse. **None of these is good enough:** words are read well, but one identifier in ten is wrong or missing, and on table-heavy pages most of them.

## What the numbers are made of

- **Tesseract's Turkish model cannot write `%`, `+`, `=`, `@`, `°`, `§`, `[`, `]`, `q`, `Q`.** Its character set (checked with `combine_tessdata -u`) lacks them, so "engel oranı %40" comes out "640" and "(%)" as "(96)". The English model has them, which is why tur+eng reads more identifiers and slightly fewer Turkish letters.
- **`₺` is in no model**, Tesseract's or RapidOCR's. "₺2.500.000" became "82.500.000" in one run: a wrong amount, silently. No engine choice fixes this; see "Safety" below.
- **Tables:** white text on dark header cells is lost, and small dotted numbers merge ("P.G. 2.7.1." to "PG.271."). The worst pages for identifiers are strategic plans, statistics yearbooks and quality standards tables.
- Two measurement artefacts were removed before these numbers: typographic apostrophes and dashes (normalised on both sides, as search will), and footnote marks glued to words in the text layer ("algoritma2"), which are not identifiers.

## Candidates still being measured

- **RapidOCR 3.9.2, PP-OCRv5 Latin recogniser (ONNX, CPU).** Spot checks: reads `%` and numbers correctly, finds lines in tables and on dark cells, but drops Turkish letters (ı to i, "Sağlik", "ilikin"); its dictionary has every Turkish letter, so this is the model, not the character set. About 6 to 8 seconds per page, several times Tesseract's cost.
- **Hybrid** ([eval/ocr/hybrid.py](../../eval/ocr/hybrid.py)): RapidOCR's detector finds the lines, dark lines are inverted, the lines are stacked into one image, Tesseract (best, tur+eng) reads it in one call. First spot checks: `%40` and Turkish letters both right, table rows read. Open: its speed measured alone, and false line detections on table borders ("ges ep"), which the quality check should drop.
- Tesseract variants: page segmentation 4 and 6, and enlarging images below 300 dpi before OCR.

## Safety, whatever the engine

OCR will not be perfect on scans. Rules for step 8 (answers):

1. Every page records where its text came from (text layer or OCR, and the engine).
2. An answer that states a number or identifier taken from an OCR'd page says so and links to the page image, so the reader can check it.
3. Low-confidence words (Tesseract reports a confidence per word) are stored, so such claims can be flagged precisely rather than for the whole page.

## Next steps

1. Finish the RapidOCR and variant runs; run every engine on the real scans (`run.py --real`).
2. Measure the hybrid alone, with a filter for non-text line detections; try a lighter detector model for speed.
3. Choose, and record the decision here and in the plan. Then wire OCR into the worker ([ocr.py](../../backend/src/synapse/knowledge/ocr.py) is ready and tested: rendering, the Tesseract adapter, and "keep whichever text scores better").
4. Speed on the reference machines (Ryzen 5 3600 and 6600H class, 16 GB) before any default is fixed.
