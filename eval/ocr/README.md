# OCR benchmark

Measures OCR engines on Turkish documents without hand labelling. The results and the decision they led to are in [docs/benchmarks/ocr.md](../../docs/benchmarks/ocr.md).

## Method

Born-digital PDF pages whose text layer passes the page quality check ([quality.py](../../backend/src/synapse/knowledge/quality.py)) have a known correct text. Each is rendered to an image and OCR'd; the output is compared with the text layer.

- 112 pages from 56 documents (municipal 42, legal 38, health 32), at most two per document, at least 400 letters, fixed seed.
- Three image conditions per page: `clean` (300 dpi), `scan` (200 dpi, grey, tilted, blurred, noisy, like the corpus's real municipal scans), `poor` (150 dpi black and white with speckles, low-quality JPEG).
- Metrics ([score.py](score.py)): character error rate; order-independent word F1; recall of words with Turkish letters; recall of identifiers (at least 4 characters with a digit: dates, decision and law numbers, amounts); median seconds per page on one thread.

## Running it

```bash
uv run --directory backend python ../eval/ocr/prepare.py         # images and truths in eval/ocr/work/
docker build -t synapse-ocr-bench eval/ocr                       # the engines, models pinned by checksum
docker run --rm -v "$PWD/eval/ocr:/bench" synapse-ocr-bench      # all engines, or name some
uv run --directory backend python ../eval/ocr/score.py           # the table
uv run --directory backend python ../eval/ocr/score.py --worst ENGINE CONDITION
```

`eval/ocr/work/` is git-ignored; it holds rendered pages of corpus documents.

## Limits

- The truth is the PDF's text layer: its reading order follows the typesetting program, so character error rates on multi-column and table pages are pessimistic. Word F1 and the recalls do not depend on order.
- Simulated degradation is not a real scanner. Real scans are checked separately on hand-verified pages.
- Timings come from Docker on the work laptop (Apple silicon), not from the target hardware; they compare engines, they do not predict production speed.
