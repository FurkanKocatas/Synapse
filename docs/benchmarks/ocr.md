# OCR engines for Turkish: benchmark

Status: **decided**, 2026-09-28. Every candidate has run on the full set on the reference hardware. No single engine reaches the targets; a combination of two does on most of them (below). A successor was measured in October 2026: PP-OCRv6 with a Turkish character language model, the application image's engine since 2026-10-05, in a vote of three readings ([ADR 0019](../adr/0019-page-ocr.md), [ADR 0020](../adr/0020-ocr-vote.md), [below](#october-2026-pp-ocrv6-with-a-turkish-language-model)).

**Decision (Furkan, 2026-09-28):** Tesseract best `tur+eng` gives the text (`tur+eng` rather than `tur`: a wrong number in the text, such as "%40" read as "640", costs more than 0.01 of Turkish-letter recall); RapidOCR, reading one line at a time, gives a second reading of the identifiers, used as search terms and as the flag for uncertain identifiers; "£" before a digit is read as "₺". Implemented in [knowledge/ocr.py](../../backend/src/synapse/knowledge/ocr.py) and [knowledge/rapid.py](../../backend/src/synapse/knowledge/rapid.py), described in [design/knowledge-base.md](../design/knowledge-base.md#ocr).

Method and scripts: [eval/ocr/](../../eval/ocr/README.md). Requirement: [ADR 0010](../adr/0010-rag-pipeline.md), ingestion rule 4 ("other engines only after they pass the Turkish character benchmark").

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
| the same, one line per recognition call | 0.746 | 0.442 | 0.927 (0.51) | 7.4 |
| Hybrid prototype (RapidOCR lines, Tesseract reading) | 0.919 | 0.950 | 0.876 (0.27) | 4.5 |

`clean` is about one point better on every column (Tesseract best tur: 0.969, 0.985, 0.910), `poor` 3 to 8 points worse. RapidOCR recognises six lines per call by default, padded to the widest; one line per call reads 41% faster and identifiers as well or better on every condition (`poor`: 0.881 against 0.866), so the product uses that. **No single engine reaches the identifier target**, and none of the Tesseract variants moves it: page segmentation 4 and 6 and enlarging are within noise of the default or worse. The hybrid, measured on the full set for the first time, is worse than plain Tesseract on every column of `scan` and `poor` and no better on `clean`; its line filter and dark-cell problems (below) would have to be solved before it is worth another run.

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
- **`₺` is in no model**, Tesseract's or RapidOCR's. Tesseract `tur+eng` reads it as "£" ("£2.500.000"); once, on the laptop, as "8", which turned "₺2.500.000" into "82.500.000", a wrong amount. The corpus's text layers hold "₺" 650 times and "£" never; in all outputs of `tur+eng`, "£" came directly before a digit 6 times, each a "₺", and once elsewhere ("£) Bu", not a lira sign; the Turkish-only model also wrote one "(£)"). So a "£" directly before a digit is read as "₺". RapidOCR writes "$" or "€" for it; those are real currencies in Turkish documents and are left alone.
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

On the real scans the extra identifiers take the municipal decision from 0.944 to 1.000 and the circular from 0.80 to 0.90, and change nothing else. With RapidOCR reading one line per call (the product's setting) and the `tur+eng` base, identifiers come to 0.974 on `clean`, 0.973 on `scan` and 0.958 on `poor` (`combine.py --second rapidocr-latin-batch1`), the real scans are unchanged, and the agreement precisions below stay within 0.03.

About two in five of the added identifiers are wrong (identifier precision falls from 0.945 to 0.909 on `scan`), so they are only fit to be **search terms**: finding a document by a number it contains matters, a wrong extra term costs little. They must not enter the text a reader or a model sees.

**Agreement as a confidence signal.** Split Tesseract's identifiers by whether RapidOCR read the same token:

| Condition | Base | Both engines agree: count, precision | Only Tesseract: count, precision |
|---|---|---|---|
| clean | Tesseract best tur | 641, 0.984 | 71, 0.479 |
| scan | Tesseract best tur | 626, 0.994 | 82, 0.427 |
| scan | Tesseract best tur+eng | 643, 0.991 | 66, 0.500 |
| poor | Tesseract best tur | 547, 0.989 | 151, 0.417 |

An identifier both engines read is right 98 to 99% of the time; one only Tesseract read is right about half the time. That is a precise way to flag uncertain numbers in answers (rule 3 below), for about one identifier in ten.

**Cost.** RapidOCR is the expensive part. Reading one line per call (the product's setting), it takes 7.4 s per page on one thread against 2.7 s for Tesseract `tur+eng`, about 10 s of CPU per scanned page; four pages at a time on this machine took 1.9 s and 0.75 s of wall time per page, about 45 minutes for 1,000 scanned pages. Alone on the machine a page is faster (5.8 s for RapidOCR's default setting against 12.6 s with four running at once), so the per-page numbers depend on how much else runs. Born-digital pages with a good text layer need neither engine.

**Memory.** One RapidOCR process grows with every image size it sees and does not give the memory back: 0.6 GB after one page, a peak of 1.7 to 2.0 GB after 40 to 60 pages, flat when the same pages come again. Neither one line per call nor switching off onnxruntime's memory pattern changed the peak much (2.0 against 2.0 GB, and 1.74 GB). The worker therefore runs RapidOCR in a child process that is replaced every 25 pages, and its memory limit on the 16 GB tier is 2.5 GB.

**What is still short of the targets:** Turkish-letter words on `scan` (0.978 against 0.98), and the worst decile of identifiers (0.72 to 0.77): table pages remain much worse than the rest, mostly the white-on-dark header cells.

## Table pages: cleaning the image first

Measured 2026-09-29 ([eval/ocr/tables.py](../../eval/ocr/tables.py), engines `tesseract-best-tur+eng-invert` and `-tables`). **Not adopted.**

Looking at the worst pages (strategic plans' indicator cards, doc-027 pages 136 and 138) changed the diagnosis. Tesseract does read most white-on-dark header cells ("Amaç (A2)", "Sorumlu Birim"). What it loses is the ruled grid: a row "P.G. 2.3.1. 100 50 20 20 20 20 20 6 AY YILDA 1" comes out "PG. 231. | 50 GAY | YILDAT", and small dots inside codes are dropped in any case ("P.G. 2.3.1." read "PG. 2.31."). Two clean-ups before Tesseract were tried: inverting filled dark areas (cells, not photos or bold headings), and painting over long thin rules.

The first inversion made things worse (identifiers on `scan` 0.928 to 0.918): the inverted cells stayed light grey, and Tesseract's layout analysis took them for pictures and skipped their text. With the cell background scaled to white, inversion alone was neutral (0.927). Both steps together, Tesseract alone, mean (worst 10%):

| Condition | Engine | Character error | Word F1 | Turkish-letter words | Identifiers |
|---|---|---|---|---|---|
| clean | tur+eng | 0.081 | 0.967 (0.862) | 0.977 (0.875) | 0.919 (0.487) |
| clean | tur+eng, cleaned | 0.094 | 0.965 (0.843) | 0.977 (0.877) | 0.931 (0.501) |
| scan | tur+eng | 0.081 | 0.959 (0.793) | 0.968 (0.801) | 0.928 (0.404) |
| scan | tur+eng, cleaned | 0.088 | 0.961 (0.813) | 0.972 (0.836) | 0.933 (0.434) |
| poor | tur+eng | 0.098 | 0.935 (0.720) | 0.936 (0.707) | 0.860 (0.199) |
| poor | tur+eng, cleaned | 0.102 | 0.935 (0.725) | 0.939 (0.735) | 0.861 (0.181) |

With RapidOCR's identifiers added (the product's reading), identifiers do not move (0.974, 0.974, 0.958); word F1 on `scan` 0.959 to 0.961, Turkish-letter words 0.968 to 0.972; on `clean` word F1 falls 0.967 to 0.965 (worst tenth 0.864 to 0.844). On the three real scans nothing improves and the committee report gets worse (word F1 0.972 to 0.963, Turkish-letter words 0.917 to 0.896).

Page by page the effect is uneven. Pages where the clean-up changes 1 to 5% of the pixels (rules) gain (word F1 +0.008, identifiers +0.025 on 55 images); pages where it changes more than 5% (large dark areas: covers, photos) lose (-0.006, -0.006 on 31); and Tesseract's layout analysis reacts to tiny changes: 0.05% of a page's pixels changed cost one page 0.09 of word F1. The two pages that prompted this got worse on identifiers. A rule deciding where to clean would be tuned on this same set of 112 pages, so the clean-up stays a benchmark engine. (Timings of this run are not comparable: it ran next to the embedding benchmark.)

## October 2026: PP-OCRv6 with a Turkish language model

OCR became the first priority on 2026-10-03, with a stricter target: 99% of words exactly right. The measure is [measure.py](../../eval/ocr/measure.py): one minus the bag-of-words error rate (OCR-D's definition), so a reading order the typesetting did not follow is not an error; the order-kept rate, identifier recall and Turkish character sensitivity are reported beside it. Two page sets came in beside the corpus benchmark above: pages of old Turkish books from Wikisource, split by book so that no book the recogniser was fine-tuned on is tested (188 pages from 44 books, with pages whose transcription covers only part of the page left out), and 24 of those pages whose truth was checked by eye against the scan (`gold`). The work is logged in the handoff repository (research/ocr-2026-10-03/results-log.md).

What raised the numbers, in order of size:

- **A character language model for decoding.** PP-OCRv6's recogniser emits a distribution per frame; prefix beam search with a 6-gram Witten-Bell model of 15 million characters of Turkish Wikipedia ([knowledge/ctc.py](../../backend/src/synapse/knowledge/ctc.py), [knowledge/charlm.py](../../backend/src/synapse/knowledge/charlm.py)) took stock PP-OCRv6 on the old books from 90.6% to 94.9%. Digits are scored by the model's probability of any digit in their place: given for free, they had turned letters into digits ("Say1").
- **Fine-tuning the recogniser for Turkish** on 300,000 synthetic lines and receipt lines (desktop GPU, 4,000 steps: about half an epoch). On the corpus benchmark it reads the `scan` condition at 98.3% with the language model (stock 96.8%). Real lines cut from the training books, added at four times their share, made it worse (punctuation and digits lost): the crops were short and nearly free of punctuation.
- **Reading order by columns** ([knowledge/reading.py](../../backend/src/synapse/knowledge/reading.py)): grouping lines into rows merged the two columns of 24 test pages line by line, which broke words hyphenated at line ends and made Turkish characters look worse than they were.
- **PaddleOCR's own detection settings and line crops.** The detection module alone shrinks a page's long side to 960 pixels; on 150 dpi scans that lost a quarter of the words.

Words exactly right (corpus benchmark: `clean` / `scan` / `poor` / three real scans):

| Engine | Corpus benchmark | Old books (188) | Gold (24) |
|---|---|---|---|
| Tesseract best `tur+eng` (the engine until 2026-10-05) | 96.8 / 96.3 / 93.6 / 95.9 | 92.5 | 93.2 |
| PP-OCRv6 stock, PaddleOCR's own decoding | 94.9 / 93.6 / 91.1 / 94.9 | 90.6 | |
| PP-OCRv6 stock + language model | 97.0 / 96.8 / 95.9 / 97.5 | 94.9 | 95.5 |
| PP-OCRv6 fine-tuned + language model | 98.3 / 98.3 / 97.0 / 99.3 | 94.8 | 95.6 |
| Vote of four (PP-OCRv6 fine-tuned and stock, PP-OCRv5 Latin mobile, Tesseract) | 98.4 / 98.4 / 97.7 / 99.7 | 95.9 | 97.0 |
| Qwen3-VL-8B (GPU, a yardstick only) | | 94.2 | 95.6 |

The vote is eval/ocr/vote.py (ROVER-style alignment to a pivot reading); the product votes three readings since 2026-10-05 (below). About 0.6 points of every engine's error on the old books was the truth's (editors' corrections, case, words glued in the transcription), which the gold pages remove; the remaining errors are mostly letters, footnote marks and short tokens.

**In the product** ([knowledge/ppocr.py](../../backend/src/synapse/knowledge/ppocr.py)): PP-OCRv6 exported to ONNX and run on onnxruntime (already a dependency) with PaddleOCR's steps re-implemented, so it reads as Paddle does (boxes in the same order, 99.9% of the likeliest characters equal). Set `ocr_ppocr_dir` to a directory with `detection.onnx`, `recognition.onnx`, `characters.json` and `charlm.npz`, and the fine-tuned recogniser with the language model gives the text of OCR'd pages; Tesseract reads them a second time for the identifiers, RapidOCR's role beside Tesseract today. On the corpus benchmark (560 identifiers per condition) the text holds 97.3 / 97.5 / 96.3% of them (`clean` / `scan` / `poor`; Tesseract's text 91.4 / 91.4 / 85.5%), 98.4 / 98.2 / 97.5% with Tesseract's extras, and wrong identifiers left unflagged are as few as today (8 / 4 / 5 against 8 / 4 / 4), with about half again as many flags on right ones. A second PP-OCR recogniser on the same detection (PP-OCRv5 Latin mobile) made the same mistakes: it flagged 44 / 20 / 66% of the wrong identifiers, Tesseract 56 / 73 / 88%. Run through the product on the 188 old-book pages it reads 94.8% of words, as eval's decode of the same recogniser does (one page differs, by one word). The detector reads a page with its long side at most 1600 pixels, not PaddleOCR's 4000: at 4000 it alone took 2.7 GB on a 300 dpi page. In the application image, under the 16 GB tier's worker limit (2.5 GB) and with two pages at a time as the worker reads them, the container peaked at 2.2 GB on the largest pages of both sets with the detector at 2500 pixels and at 1.2 GB at 1600, which reads as well, within noise: corpus benchmark 98.3 / 98.5 / 97.1 at 1600 against 98.3 / 98.3 / 97.1 at 2500, old books 94.6 against 94.7, gold pages 95.4 against 95.5 (95.6 at the page's own size). The worker's own process held 0.8 GB beside RapidOCR's child after a day's work, so 2500 would leave too little room. The two engines read a page at the same time, each in a process of its own, and onnxruntime uses four threads (`ocr_threads`): on eight typical pages (four from the old books, four `scan` pages) a page takes 13.0 s at the median, against 4.4 s for Tesseract with RapidOCR (16.8 s at 2500 pixels; one thread is about three times as slow). Most of it is the recogniser, and nearly three quarters of that its backbone's convolutions; the output layer of 18,710 classes is 3%. Under memory pressure from other work, and once without it, the detector returned a map of NaN for a page it otherwise reads normally (the page came out empty); every model output is now checked and run again when it is not finite, the page goes to a fresh child process when it is not finite twice, and it is reported as an OCR error after that, so the page keeps its text. The application image fetches the models from this repository's release `ocr-models-1`, pinned by checksum, and sets the directory ([ADR 0019](../adr/0019-page-ocr.md)); unset, Tesseract gives the text and RapidOCR the second reading as before.

**The vote in the product** ([knowledge/vote.py](../../backend/src/synapse/knowledge/vote.py), [ADR 0020](../adr/0020-ocr-vote.md)): PP-OCRv6's fine-tuned recogniser (the pivot), PP-OCRv5's Latin mobile recogniser on the same lines with the same language model, and Tesseract, voted word by word as eval/ocr/vote.py does, without its lexicon (wordfreq: CC BY-SA data, worth 0.15 points on old books; the character language model in its place was worth nothing), with letters Turkish has not mapped first and the pivot's circumflexes on the chosen words. The text keeps the pivot's lines and the punctuation around its words. Measured in eval first, without a lexicon and with the detector at 1600: the fine-tuned recogniser must be the pivot (stock PP-OCRv6 as the pivot read the corpus's `clean` and `scan` pages worse than no vote), and stock PP-OCRv6 as a fourth voice added 0.2 to 0.3 points on old books and nothing on the corpus for about 10 s a page. Run in the application image, two pages at a time, the product's vote read the corpus benchmark at 98.4 / 97.6 / 98.5 (`clean` / `poor` / `scan`; PP-OCRv6 alone 98.3 / 97.1 / 98.5; eval's vote the same 98.4 / 97.6 / 98.5), the old books at 95.3 (94.6) and the gold pages at 96.2 (95.4); the container peaked at 1.5 GB. On the corpus, wrong identifiers in the text were fewer (13 / 31 / 11 against 14 / 43 / 14), as many left unflagged (8 / 5 / 4). A page takes 15.8 s against 12.8 s (eight typical pages, one at a time). On the old books the product's Latin voice reads 94.5 where eval's read 94.9: its export matches Paddle (0.25% of characters differ on the same boxes, the fine-tuned recogniser's 0.31%), but the detector's boxes at 1600 pixels suit it less than the page's own size; with eval's Latin readings the product's vote reads the old books at 95.5.

**Pages scanned sideways** (since 2026-10-06; [knowledge/ppocr.py](../../backend/src/synapse/knowledge/ppocr.py), `upright`): when at least 60% of a page's lines, and at least five, are taller than wide, the eight largest are read both ways, the page is turned the way that reads with more confidence and its lines are found again. A table scanned sideways in the corpus (doc-001 page 11) read as noise before and reads as the table now; the rule never held on the benchmark's 878 ordinary pages. Tesseract, the third voice, does not turn the page: there it reads noise, the two PP-OCR voices carry the vote, and its identifiers flag the text's as uncertain.

Next: line boxes that suit the Latin voice (0.2 points on old books); full-line real training data; more gold pages, with small print, to check the detector at 1600 pixels further.

## Safety, whatever the engine

OCR will not be perfect on scans. Rules for step 8 (answers):

1. Every page records where its text came from (text layer or OCR, and the engine).
2. An answer that states a number or identifier taken from an OCR'd page says so and links to the page image, so the reader can check it.
3. Uncertain identifiers are stored, so such claims can be flagged precisely rather than for the whole page: Tesseract's per-word confidence, and, if the combination is adopted, whether the second engine read the same token.

## Next steps

1. Table pages: done as far as whole-page clean-up goes (above, not adopted). What is left: find the table's grid and read each cell on its own (Tesseract with one line per cell), and more real table scans to measure it on.
2. Transcribe more real scans, tables especially: three pages cannot carry more than this decision.
3. RapidOCR speed: detection takes 1.3 s of a page's 5.8 s alone, recognition the rest; recognising only lines that may hold identifiers could cut most of it.
4. Search (step 7): match long letter-and-digit identifiers with spaces removed; compare identifiers with a leading currency sign stripped, so "$5.000.000" from RapidOCR confirms "₺5.000.000" from Tesseract.
5. Answers (step 8): flag numbers from `uncertain_identifiers`.
