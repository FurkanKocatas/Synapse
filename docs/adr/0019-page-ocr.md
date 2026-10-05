# 0019. Page OCR: PP-OCRv6 with a Turkish language model

- Status: accepted
- Date: 2026-10-05

## Context

Pages without a usable text layer are read by two engines ([ADR 0010](0010-rag-pipeline.md), ingestion rule 4): one gives the text, the other reads the page again for its identifiers (dates, decision numbers, amounts). The engines chosen on 2026-09-28 were Tesseract's best `tur+eng` for the text and RapidOCR for the second reading ([benchmarks/ocr.md](../benchmarks/ocr.md)). On 2026-10-03 OCR became the first priority, with 99% of words exactly right as the target. Measured since ([benchmarks/ocr.md](../benchmarks/ocr.md#october-2026-pp-ocrv6-with-a-turkish-language-model)):

- PP-OCRv6's recogniser fine-tuned for Turkish and decoded with a character 6-gram language model of Turkish Wikipedia reads more words exactly than Tesseract on every page set: the corpus benchmark 98.3 / 98.3 / 97.0% against 96.8 / 96.3 / 93.6% (`clean` / `scan` / `poor`), old Turkish books 94.8% against 92.5%, pages with hand-checked truth 95.6% against 93.2%.
- Its text holds more of the identifiers: 97.3 / 97.5 / 96.3% against 91.4 / 91.4 / 85.5%. With Tesseract as the second reading, wrong identifiers left unflagged are as few as with today's pair (8 / 4 / 5 against 8 / 4 / 4). A second PP-OCR recogniser on the same detection made the text's own mistakes and flagged fewer of them.
- The product's implementation ([knowledge/ppocr.py](../../backend/src/synapse/knowledge/ppocr.py), onnxruntime, already a dependency) reads as the evaluation does: 94.8% of words on the old books in both.
- In the application image, under the 16 GB tier's worker limit (2.5 GB) and with two pages at a time, the container peaked at 2.2 GB on the largest pages of both sets with the detector reading a page at up to 2500 pixels, and at 1.2 GB at up to 1600 pixels, which reads as well: corpus benchmark 98.3 / 98.5 / 97.1%, old books 94.6%, hand-checked pages 95.4% (95.5% at 2500). The worker's own process held 0.8 GB beside RapidOCR's child after a day's work, so 2500 would leave too little room.
- It is slower: on eight typical pages a page takes 13.0 s at the median (four threads, both engines at the same time), against 4.4 s for Tesseract with RapidOCR.

## Decision

1. The application image carries PP-OCRv6's model directory and sets `SYNAPSE_OCR_PPOCR_DIR`. PP-OCRv6 with the language model gives the text of pages that need OCR; Tesseract reads them a second time for the identifiers. RapidOCR is the second reading only where the setting is unset (a worker run on a host without the models).
2. The model files are assets of a release of this repository, `ocr-models-1`: `detection.onnx`, `recognition.onnx`, `characters.json`, `charlm.npz`. The Dockerfile fetches each by URL with its SHA-256, as it does Tesseract's models, so the running containers need no network. A new model set is a new release under a new tag; the files of a published release are never replaced. `docs/licences.md` lists them.
3. The detector reads a page with its long side at 1600 pixels at most. The two engines read a page at the same time, each in a process of its own, and the OCR engines' onnxruntime uses four threads by default (`ocr_threads`).

## Consequences

- Scanned pages get better text and more of their identifiers; pages read before keep theirs until they are read again (`ocr_engine` tells the two apart).
- The image is 227 MB larger, and building it needs GitHub's release downloads.
- OCR takes about three times as long per page, and more of the CPU while it runs (four threads beside Tesseract's one).
- `charlm.npz` is statistics of Wikipedia text and carries its licence, CC BY-SA 4.0: the release and the third-party notices give the attribution.
- A model trained again means a new release and new checksums in the Dockerfile, measured first as in [benchmarks/ocr.md](../benchmarks/ocr.md).

## Alternatives considered

- **Models in the repository** (plain or Git LFS): every clone would carry them for good, and LFS's bandwidth quota would run out on CI's image builds.
- **Our own download server**: one more service to keep running, for files GitHub serves next to the code.
- **Stock PP-OCRv6 instead of the fine-tuned recogniser**: as good on the old books (94.9%), worse on the corpus benchmark (97.0 / 96.8 / 95.9%).
- **RapidOCR as the second reading beside PP-OCRv6**: its child process (up to 2 GB) and PP-OCRv6's would not fit the worker's limit together.
- **The detector at a long side of 2500 pixels**: as accurate (corpus 98.3 / 98.3 / 97.1%, old books 94.7%), but 2.2 GB at the peak instead of 1.2 and a page in 16.8 s instead of 13.0.
- **The vote of four engines** (95.9% on the old books): not in the product yet; it needs two more recognisers' time and memory.
