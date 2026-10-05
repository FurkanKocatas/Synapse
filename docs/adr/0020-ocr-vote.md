# 0020. Page OCR: a vote of three readings

- Status: accepted
- Date: 2026-10-05

## Context

[ADR 0019](0019-page-ocr.md) made PP-OCRv6 with the Turkish language model the text of pages that need OCR, and Tesseract the second reading of their identifiers. In the evaluation, a vote of several engines' readings (eval/ocr/vote.py: each reading aligned word by word to a pivot reading, the majority taken at every word) read more words than any engine alone. Measured without the evaluation's lexicon (Turkish word frequencies from wordfreq: CC BY-SA data and a new dependency, worth 0.15 points on old books; the character language model in its place was worth nothing), with the detector at 1600 pixels ([benchmarks/ocr.md](../benchmarks/ocr.md)), words exactly right:

| Voices, the pivot first | Old books (188) | Gold pages (24) | Corpus `clean` / `poor` / `scan` |
|---|---|---|---|
| PP-OCRv6 fine-tuned alone (ADR 0019) | 94.7 | 95.4 | 98.3 / 97.1 / 98.5 |
| PP-OCRv6 fine-tuned, PP-OCRv5 Latin mobile, Tesseract | 95.4 | 96.4 | 98.4 / 97.6 / 98.5 |
| the same and stock PP-OCRv6 | 95.6 | 96.7 | 98.3 / 97.5 / 98.5 |
| stock PP-OCRv6 as the pivot, four voices | 95.7 | 96.7 | 97.9 / 97.2 / 98.0 |

- The fine-tuned recogniser must be the pivot: with stock PP-OCRv6 as the pivot, the corpus benchmark's `clean` and `scan` pages read worse than the fine-tuned recogniser alone.
- The Latin recogniser is a mobile model (8 MB) that reads the lines the detector has found anyway. Stock PP-OCRv6 would cost as much as the fine-tuned recogniser, about 10 s a page, for 0.2 to 0.3 points on old books and nothing on the corpus.
- Circumflexes taken from the pivot ("malî", which the other voices drop) add up to 0.1 points; Turkish letters taken from it, nothing.
- The product's vote reads as the evaluation's: on the evaluation's own readings it gave 95.5% on the old books (the evaluation 95.4%), and in the application image, with two pages at a time under the worker's 2.5 GB limit, the corpus benchmark 98.4 / 97.6 / 98.5% (PP-OCRv6 alone 98.3 / 97.1 / 98.5%), the old books 95.3% (94.6%) and the gold pages 96.2% (95.4%). The container peaked at 1.5 GB. Wrong identifiers in the text were fewer (13 / 31 / 11 against 14 / 43 / 14 on `clean` / `poor` / `scan`), as many left unflagged (8 / 5 / 4). One page at a time, a page took 15.8 s against 12.8 s (eight typical pages, four threads).

## Decision

1. A page that needs OCR is read three times: by PP-OCRv6's fine-tuned recogniser with the language model (the pivot), by PP-OCRv5's Latin mobile recogniser on the same lines with the same language model, and by Tesseract. The three readings are voted word by word ([knowledge/vote.py](../../backend/src/synapse/knowledge/vote.py)) as eval/ocr/vote.py does, without a lexicon: letters Turkish has not are mapped to the Turkish letter they look like first, and the chosen word takes the pivot's circumflexes. The text keeps the pivot's lines and the punctuation around its words.
2. The Latin recogniser's files are assets of the release `ocr-models-2` (`latin-recognition.onnx`, `latin-characters.json`), fetched into the model directory with the files of `ocr-models-1`, each pinned by SHA-256. The worker votes when the model directory holds them, and reads as ADR 0019 describes when it does not.
3. Tesseract's reading stays the second reading of the identifiers: those it adds are search terms, the text's identifiers it lacks are flagged.

## Consequences

- More words right on scanned pages, most on poor scans and old prints, and fewer wrong identifiers in the text; a page takes about 3 s more.
- `ocr_engine` records the vote and its voices: `vote-ppocrv6-tr-lm+ppocrv5-latin-lm+tesseract-tur+eng`.
- rapidfuzz (MIT), already used by the evaluation, becomes a runtime dependency: the vote's alignment.
- The Latin recogniser reads the old books worse in the product than in the evaluation (94.5% against 94.9%): the detector's boxes at 1600 pixels suit it less than the page's own size, while the fine-tuned recogniser hardly notices. A better box for it is the next gain to look for.

## Alternatives considered

- **Stock PP-OCRv6 as a fourth voice**: about 10 s more a page for 0.2 to 0.3 points on old books and nothing on modern documents.
- **Stock PP-OCRv6 as the pivot**: best on old books, worse than no vote on the corpus benchmark.
- **The lexicon**: 0.15 points on old books for CC BY-SA data and a new dependency; the character language model as a lexicon did not replace it.
- **PP-OCR voices only** (fine-tuned, stock and Latin, no Tesseract): their errors are alike; the corpus benchmark read worse (98.0 / 97.2 / 98.1%).
