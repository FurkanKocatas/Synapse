"""PaddleOCR-VL (layout, then the 0.9B recogniser per region) over the OCR benchmark's images.

    python eval/ocr/paddle_vl.py --images DIR [--images DIR] --out DIR [--version v1.6]
    python eval/ocr/paddle_vl.py --out DIR --retext

Runs in an environment with PaddlePaddle and ``paddleocr[doc-parser]`` (docs/research/ocr.md;
the model card's own pipeline, on a CUDA GPU). Every ``<page>.<condition>.png`` becomes
``<out>/<engine>/<page>.<condition>.txt`` as measure.py reads it: the blocks' text in the
pipeline's reading order, markup taken out (plaintext.py). The pipeline's own result is kept
beside it (``raw/<page>.<condition>.json``), so ``--retext`` writes the text again from it
without reading the pages again; the seconds per page go to ``timings.json``. Pages already
done are skipped, so a run that stops can be started again.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "huggingface")

from plaintext import plain

IMAGES = frozenset({".png", ".jpg", ".jpeg"})
# Blocks that hold no text of the page.
PICTURES = frozenset({"image", "chart", "seal_image", "figure"})


def page_text(result: dict) -> str:
    blocks = result.get("res", result).get("parsing_res_list", [])
    parts = [
        plain(str(b.get("block_content") or ""))
        for b in blocks
        if b.get("block_label") not in PICTURES
    ]
    return "\n".join(part for part in parts if part)


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("--images", type=Path, action="append", default=[])
    options.add_argument("--out", type=Path, required=True)
    options.add_argument("--version", default="v1.6")
    options.add_argument("--engine", default="paddleocr-vl-1.6")
    options.add_argument("--retext", action="store_true")
    # The recogniser served by vLLM (its model card's accelerated path), e.g.
    # http://127.0.0.1:8000/v1; without it, PaddlePaddle runs it itself (slower).
    options.add_argument("--server")
    args = options.parse_args()
    target = args.out / args.engine
    (target / "raw").mkdir(parents=True, exist_ok=True)
    if args.retext:
        for raw in sorted((target / "raw").glob("*.json")):
            text = page_text(json.loads(raw.read_text(encoding="utf-8")))
            (target / f"{raw.stem}.txt").write_text(text, encoding="utf-8")
        return

    from paddleocr import PaddleOCRVL  # noqa: PLC0415  (only this script's environment has it)

    timings_file = target / "timings.json"
    timings = json.loads(timings_file.read_text()) if timings_file.exists() else {}
    served = {"vl_rec_backend": "vllm-server", "vl_rec_server_url": args.server}
    pipeline = PaddleOCRVL(pipeline_version=args.version, **(served if args.server else {}))
    images = sorted(p for folder in args.images for p in folder.iterdir() if p.suffix in IMAGES)
    for number, image in enumerate(images, start=1):
        if (target / f"{image.stem}.txt").exists():
            continue
        started = time.perf_counter()
        (result,) = list(pipeline.predict(str(image)))
        seconds = time.perf_counter() - started
        raw = result.json
        (target / "raw" / f"{image.stem}.json").write_text(
            json.dumps(raw, ensure_ascii=False), encoding="utf-8"
        )
        (target / f"{image.stem}.txt").write_text(page_text(raw), encoding="utf-8")
        timings[image.stem] = round(seconds, 2)
        timings_file.write_text(json.dumps(timings, indent=1), encoding="utf-8")
        print(f"{number}/{len(images)} {image.stem} {seconds:.1f}s", flush=True)


if __name__ == "__main__":
    main()
