# OCR engines for Turkish: benchmark

Status: **measured, decision pending**, 2026-09-28. Every candidate has now run on the full set on the reference hardware. No single engine reaches the targets; a combination of two does on most of them (below). Method and scripts: [eval/ocr/](../../eval/ocr/README.md). Requirement: [ADR 0010](../adr/0010-rag-pipeline.md), ingestion rule 4 ("other engines only after they pass the Turkish character benchmark").

Targets before choosing: identifiers at least 0.97 on `clean` and `scan`, Turkish-letter words at least 0.98, and a worst decile that is not a cliff.

## Method in one paragraph

112 born-digital pages from 56 corpus documents (municipal 42, legal 38, health 32) are rendered to images in three conditions: `clean` 300 dpi; `scan` 200 dpi grey, tilted, blurred, noisy (the corpus's real municipal scans are 200 dpi); `poor` 150 dpi black and white, speckled, low-quality JPEG. The OCR output is compared with the page's own text layer. Metrics: character error rate; order-independent word F1; recall of words with Turkish letters (`tr_recall`); recall of identifiers (`id_recall`: tokens of at least 4 characters, at least half digits: dates, decision and law numbers, amounts). Three real scanned pages are transcribed by hand ([eval/ocr/real/](../../eval/ocr/real/)) to check that the simulation holds. The target for identifiers is the ADR 0010 bar for exact-identifier retrieval: an OCR engine that loses one identifier in ten cannot reach it.

## Hardware and timing

All numbers below come from the reference machine class: AMD Ryzen 5 6600H (6 cores), 16 GB, Linux, Docker, nothing else heavy running. Every engine reads each page with **one thread**, four pages at a time; the seconds are the median per page. (Before 2026-09-28 evening, RapidOCR and the hybrid used every core through onnxruntime while Tesseract used one, so their earlier timings were not comparable; `run.py` now limits both.) The first runs, on an Apple laptop, are reproduced within 0.01 on every mean; worst-decile values move by up to 0.03.

## Single engines

`scan` condition, mean over pages (worst 10% of pages in brackets):

| Engine | Word F1 | Turkish-letter words | Identifiers | Seconds per page |
|---|---|---|---|---|
| Tesseract `tessdata_fast` tur (identical to Debian's package) | 0.956 | 0.975 | 0.885 (0.23) | 1.0 |
| Tesseract `tessdata_best` tur | 0.960 | 0.978 | 0.914 (0.35) | 2.3 |
| Tesseract `tessdata_best` tur+eng | 0.959 | 0.968 | 0.928 (0.40) | 2.7 |
| the same, page segmentation 4 | 0.960 | 0.968 | 0.919 (0.41) | 2.7 |
| the same, page segmentation 6 | 0.943 | 0.964 | 0.914 (0.44) | 2.6 |
| the same, enlarged to 300 dpi first | 0.959 | 0.971 | 0.919 (0.43) | 3.3 |
| RapidOCR 3.9.2 (PP-OCRv5 Latin, ONNX) | 0.744 | 0.439 | 0.925 (0.49) | 12.6 |
| Hybrid prototype (RapidOCR lines, Tesseract reading) | 0.919 | 0.950 | 0.876 (0.27) | 4.5 |

`clean` is about one point better on every column (Tesseract best tur: 0.969, 0.985, 0.910), `poor` 3 to 8 points worse. **No single engine reaches the identifier target**, and none of the Tesseract variants moves it: page segmentation 4 and 6 and enlarging are within noise of the default or worse. The hybrid, measured on the full set for the first time, is worse than plain Tesseract on every column of `scan` and `poor` and no better on `clean`; its line filter and dark-cell problems (below) would have to be solved before it is worth another run.

**Real scans** (three hand-verified pages: a municipal committee report at 200 dpi, a municipal decision at 424 dpi, a ministry circular at 283 dpi):

| Engine | Character error rate | Word F1 | Turkish-letter words | Identifiers | Seconds per page |
|---|---|---|---|---|---|
| Tesseract best tur | 0.008 to 0.031 | 0.960 to 0.978 | 0.917 to 1.000 | 0.80 to 1.00 | 0.9 to 2.4 |
| Tesseract best tur+eng | 0.012 to 0.033 | 0.954 to 0.972 | 0.917 to 0.977 | 0.80 to 1.00 | 1.2 to 2.7 |
| the same, page segmentation 4 | 0.006 to 0.033 | 0.960 to 0.982 | 0.958 to 1.000 | 0.80 to 1.00 | 1.2 to 2.7 |
| the same, enlarged to 300 dpi | 0.012 to 0.046 | 0.941 to 0.968 | 0.917 to 0.966 | 0.30 to 1.00 | 1.5 to 2.7 |
| Hybrid prototype | 0.031 to 0.405 | 0.733 to 0.965 | 0.896 to 0.991 | 0.40 to 0.94 | 5.1 to 9.2 |

On real text-heavy scans Tesseract is much better than on the simulated table pages. The identifiers it missed: the small number under a barcode (read "001408" for "00140812961"), and a 32-character verification code split by a space ("55E3D13EBFB4473F9 C6DD3A6CA62C1EB"; the Turkish-only model also read one "1" as "İ", tur+eng did not). Enlarging broke the circular's identifiers (0.30). The hybrid detects signatures and stamps as lines and reads them as garbage.

## What the numbers are made of

- **Tesseract's Turkish model cannot write `%`, `+`, `=`, `@`, `°`, `§`, `[`, `]`, `q`, `Q`.** Its character set (checked with `combine_tessdata -u`) lacks them, so "engel oranı %40" comes out "640" and "(%)" as "(96)". The English model has them, which is why tur+eng reads more identifiers and slightly fewer Turkish letters.
- **`₺` is in no model**, Tesseract's or RapidOCR's. Tesseract reads it as "£" ("£2.500.000"), three times in this set; once, on the laptop, as "8", which turned "₺2.500.000" into "82.500.000", a wrong amount.
- **Where the identifiers go** (Tesseract best tur+eng, `scan`: 60 of 730 missed). 45 of the 60 are on ten pages, all tables: strategic plans, performance tables, a statistics yearbook. By kind: 30 misread or read fewer times than they occur (repeated table codes "5.1.1", "2.8.2" read as "2.7.2", "3.1.5." as "34.5."); 24 not in the output at all, of which the year headers in white-on-dark cells ("2025 2026 2027 2028 2029" read as "100% 2 2 2") are the largest group; 4 split or glued to a neighbour; 2 a dropped symbol.
- **Measurement artefacts still in the numbers** (left in so the numbers stay comparable with earlier runs; together about one point of identifier recall): footnote marks glued to a closing bracket in the text layer ("(…)31", "md.)43"), a broken text layer whose truth is wrong ("SKB -159" where the page shows "140-159", which Tesseract reads correctly), and numbers with a Turkish suffix counted as identifiers only because of the suffix ("351'i", "24'ü"). Two artefacts were already removed before these numbers: typographic apostrophes and dashes (normalised on both sides, as search will), and footnote marks glued to words ("algoritma2").

## Two engines together

RapidOCR and Tesseract miss different identifiers. Choosing the better engine per page (with the truth, so an upper bound) gives 0.974 on `scan`; a practical version needs no truth: keep Tesseract's text, and add the identifiers RapidOCR read that Tesseract's output lacks. [combine.py](../../eval/ocr/combine.py) scores that from the existing outputs.

Tesseract's text plus RapidOCR's extra identifiers (mean, worst 10% in brackets):

| Condition | Base | Word F1 | Turkish-letter words | Identifiers |
|---|---|---|---|---|
| clean | Tesseract best tur | 0.969 (0.87) | **0.986** (0.91) | **0.970** (0.72) |
| clean | Tesseract best tur+eng | 0.967 (0.86) | 0.978 (0.88) | **0.975** (0.76) |
| scan | Tesseract best tur | 0.961 (0.81) | 0.978 (0.85) | **0.975** (0.77) |
| scan | Tesseract best tur+eng | 0.959 (0.80) | 0.968 (0.80) | **0.973** (0.75) |
| poor | Tesseract best tur | 0.936 (0.72) | 0.944 (0.72) | 0.952 (0.65) |

On the real scans the extra identifiers take the municipal decision from 0.944 to 1.000 and the circular from 0.80 to 0.90, and change nothing else.

About two in five of the added identifiers are wrong (identifier precision falls from 0.945 to 0.909 on `scan`), so they are only fit to be **search terms**: finding a document by a number it contains matters, a wrong extra term costs little. They must not enter the text a reader or a model sees.

**Agreement as a confidence signal.** Split Tesseract's identifiers by whether RapidOCR read the same token:

| Condition | Base | Both engines agree: count, precision | Only Tesseract: count, precision |
|---|---|---|---|
| clean | Tesseract best tur | 641, 0.984 | 71, 0.479 |
| scan | Tesseract best tur | 626, 0.994 | 82, 0.427 |
| scan | Tesseract best tur+eng | 643, 0.991 | 66, 0.500 |
| poor | Tesseract best tur | 547, 0.989 | 151, 0.417 |

An identifier both engines read is right 98 to 99% of the time; one only Tesseract read is right about half the time. That is a precise way to flag uncertain numbers in answers (rule 3 below), for about one identifier in ten.

**Cost.** RapidOCR is the expensive part: 12.6 s per page on one thread against 2.3 s for Tesseract, so about 15 s of CPU per scanned page; four pages at a time on this machine took 3.1 s and 0.6 s of wall time per page, about one hour for 1,000 scanned pages. Four RapidOCR processes raised memory use by about 3.5 GB. Born-digital pages with a good text layer need neither engine.

**What is still short of the targets:** Turkish-letter words on `scan` (0.978 against 0.98), and the worst decile of identifiers (0.72 to 0.77): table pages remain much worse than the rest, mostly the white-on-dark header cells.

## Safety, whatever the engine

OCR will not be perfect on scans. Rules for step 8 (answers):

1. Every page records where its text came from (text layer or OCR, and the engine).
2. An answer that states a number or identifier taken from an OCR'd page says so and links to the page image, so the reader can check it.
3. Uncertain identifiers are stored, so such claims can be flagged precisely rather than for the whole page: Tesseract's per-word confidence, and, if the combination is adopted, whether the second engine read the same token.

## Next steps

1. Decide with Furkan: adopt the combination (base Tesseract best tur or tur+eng; RapidOCR identifiers as search terms and as the agreement flag), at about six times the OCR time of Tesseract alone; or Tesseract alone with the gaps above.
2. Table pages: find why the white-on-dark header cells are lost (save the crops and look), and measure a fix on the worst ten pages.
3. Read "£" before a digit as "₺" (the pound sign does not occur in Turkish documents): measure it, like every other change.
4. Transcribe more real scans, tables especially: three pages cannot carry a decision.
5. RapidOCR speed: measure detection and recognition separately; running recognition only on lines that contain digits may cut most of its time.
6. Search-side mitigation for split codes: match long letter-and-digit identifiers with spaces removed (step 7).
7. Then wire OCR into the worker ([ocr.py](../../backend/src/synapse/knowledge/ocr.py) is ready and tested: rendering, the Tesseract adapter, and "keep whichever text scores better").
