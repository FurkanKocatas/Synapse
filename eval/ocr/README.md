# OCR benchmark

Measures OCR engines on Turkish documents without hand labelling. The results and the decision they led to are in [docs/benchmarks/ocr.md](../../docs/benchmarks/ocr.md).

## Method

Born-digital PDF pages whose text layer passes the page quality check ([quality.py](../../backend/src/synapse/knowledge/quality.py)) have a known correct text. Each is rendered to an image and OCR'd; the output is compared with the text layer.

- 112 pages from 56 documents (municipal 42, legal 38, health 32), at most two per document, at least 400 letters, fixed seed.
- Three image conditions per page: `clean` (300 dpi), `scan` (200 dpi, grey, tilted, blurred, noisy, like the corpus's real municipal scans), `poor` (150 dpi black and white with speckles, low-quality JPEG).
- Metrics ([score.py](score.py)): character error rate; order-independent word F1; recall of words with Turkish letters; recall of identifiers (at least 4 characters with a digit: dates, decision and law numbers, amounts); median seconds per page on one thread.

## Running it

```bash
uv run --directory backend python ../eval/ocr/prepare.py         # images, truths and real scans in eval/ocr/work/
docker build -t synapse-ocr-bench eval/ocr                       # the engines, models pinned by checksum
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/eval/ocr:/bench" synapse-ocr-bench   # all engines, or name some
uv run --directory backend python ../eval/ocr/score.py           # the table
uv run --directory backend python ../eval/ocr/score.py --worst ENGINE CONDITION
uv run --directory backend python ../eval/ocr/combine.py         # Tesseract text + RapidOCR identifiers
```

`eval/ocr/work/` is git-ignored; it holds rendered pages of corpus documents. `--user` matters on Linux: without it the container writes its output as root into the bind-mounted `work/out/` (Docker Desktop on macOS hides this). The image needs no network at run time.

## Decoding PP-OCRv6 with a language model

PP-OCRv6's recogniser gives a character distribution per frame; reading the likeliest character each time (greedy) throws away the second guesses where Turkish letters often sit. The product decodes them with a Turkish character language model (`backend/src/synapse/knowledge/ctc.py`, `charlm.py`) and puts the lines in reading order (`reading.py`: rows, and columns one after the other). For comparing decoders without running the recogniser again, the distributions are dumped once (needs paddleocr 3.x):

```bash
python eval/ocr/char_lm.py train --parquet TURKISH_TEXT.parquet --out char_lm6.pkl          # 6-gram, 15M characters
uv run --directory backend python ../eval/ocr/char_lm.py pack --lm char_lm6.pkl --out char_lm6.npz   # what the product loads, 90 MB
python eval/ocr/ctc_dump.py --images DIR --out DUMP [--rec-dir FINE_TUNED | --rec-model NAME] [--device gpu]
uv run --directory backend python ../eval/ocr/ctc_decode.py --dump DUMP --out eval/ocr/work/out/ENGINE --lm char_lm6.npz
```

`ctc_dump.py` detects and crops lines as PaddleOCR's own pipeline does, as does the product's onnxruntime engine (`knowledge/ppocr.py`); `ctc_decode.py` runs the product's decoder on the dump.

## Limits

- The truth is the PDF's text layer: its reading order follows the typesetting program, so character error rates on multi-column and table pages are pessimistic. Word F1 and the recalls do not depend on order.
- Simulated degradation is not a real scanner. Real scans are checked separately on hand-verified pages.
- Timings are per page on one thread, four pages at a time, in Docker on the machine that runs the benchmark (the published numbers: a Ryzen 5 6600H, the reference hardware). They compare engines; production speed also depends on how many pages run in parallel.
