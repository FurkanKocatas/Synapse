"""Run every OCR engine over the benchmark images (inside the synapse-ocr-bench container).

    docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/eval/ocr:/bench" synapse-ocr-bench \
        [--real] [ENGINE ...]

``--real`` runs only the real scans in /bench/work/real/ (hand-verified truths in real/).

Reads /bench/work/images/*.png, writes /bench/work/out/<engine>/<image>.txt and timings in
/bench/work/out/<engine>/timings.json. Each image is OCR'd by one process with one thread, so the
time per page is comparable across engines. Pages run BENCH_WORKERS at a time (default 4; use
2 for RapidOCR, whose processes take about 1 GB each). A worker that dies (for example out of
memory) stops the run with an error instead of hanging it, as multiprocessing.Pool would.
"""

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

os.environ["OMP_THREAD_LIMIT"] = "1"  # Tesseract: one thread per page
# RapidOCR (onnxruntime) uses every core by default: about six on a 6-core machine, measured.
ONE_THREAD = {
    "EngineConfig.onnxruntime.intra_op_num_threads": 1,
    "EngineConfig.onnxruntime.inter_op_num_threads": 1,
}

WORK = Path("/bench/work")
IMAGES = sorted((WORK / "images").glob("*.png"))
REAL = sorted((WORK / "real").glob("*.png"))


def tesseract(
    tessdata: str | None,
    languages: str,
    *,
    psm: int = 3,
    upscale_below_dpi: int = 0,
    clean: str | None = None,
) -> Callable[[Path], str]:
    """``upscale_below_dpi``: images whose width suggests less than this resolution on A4 are
    enlarged to it first (Tesseract is trained on text about 300 dpi high). ``clean``: the page
    is cleaned up first (tables.py): "invert" inverts dark cells, "tables" also removes lines."""

    def run(image: Path) -> str:
        source = image
        if clean:
            import cv2
            import tables

            grey = cv2.imread(str(image), cv2.IMREAD_GRAYSCALE)
            cleaned = tables.clean(grey, invert=True, lines=clean == "tables")
            source = Path(f"/tmp/{image.stem}.clean.png")
            cv2.imwrite(str(source), cleaned)
        if upscale_below_dpi:
            from PIL import Image

            with Image.open(image) as picture:
                dpi = picture.width / 8.27  # A4 width in inches
                if dpi < upscale_below_dpi:
                    factor = upscale_below_dpi / dpi
                    size = (round(picture.width * factor), round(picture.height * factor))
                    source = Path(f"/tmp/{image.stem}.up.png")
                    picture.resize(size, Image.Resampling.LANCZOS).save(source)
        command = ["tesseract", str(source), "-", "-l", languages, "--oem", "1", "--psm", str(psm)]
        if tessdata:
            command += ["--tessdata-dir", tessdata]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        if source != image:
            source.unlink()
        return result.stdout

    return run


_rapid: dict[int, Any] = {}


def rapidocr(image: Path, batch: int = 6) -> str:
    """``batch``: lines recognised per call. RapidOCR's default is 6; the lines of a batch are
    padded to the widest, so the batch size changes what is read, not only how fast."""
    if batch not in _rapid:
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

        # The Latin recogniser exists for PP-OCRv5, in the mobile size only.
        _rapid[batch] = RapidOCR(
            params={
                "Rec.lang_type": LangRec.LATIN,
                "Rec.ocr_version": OCRVersion.PPOCRV5,
                "Rec.model_type": ModelType.MOBILE,
                "Rec.rec_batch_num": batch,
                "Global.log_level": "error",
                **ONE_THREAD,
            }
        )
    output = _rapid[batch](str(image), use_det=True, use_cls=True, use_rec=True)
    return "\n".join(output.txts or ())


def hybrid_engine(image: Path) -> str:
    import hybrid

    return hybrid.recognize(image, "/models/best", "tur+eng", engine_params=ONE_THREAD)


ENGINES: dict[str, Callable[[Path], str]] = {
    "tesseract-debian-tur": tesseract(None, "tur"),
    "tesseract-fast-tur": tesseract("/models/fast", "tur"),
    "tesseract-best-tur": tesseract("/models/best", "tur"),
    "tesseract-best-tur+eng": tesseract("/models/best", "tur+eng"),
    "rapidocr-latin": rapidocr,
    "rapidocr-latin-batch1": lambda image: rapidocr(image, batch=1),
    "tesseract-best-tur+eng-psm4": tesseract("/models/best", "tur+eng", psm=4),
    "tesseract-best-tur+eng-psm6": tesseract("/models/best", "tur+eng", psm=6),
    "tesseract-best-tur+eng-up300": tesseract("/models/best", "tur+eng", upscale_below_dpi=300),
    "tesseract-best-tur+eng-invert": tesseract("/models/best", "tur+eng", clean="invert"),
    "tesseract-best-tur+eng-tables": tesseract("/models/best", "tur+eng", clean="tables"),
    "hybrid-tur+eng": hybrid_engine,
}


def work(job: tuple[str, Path]) -> tuple[str, float]:  # runs in a pool process
    engine, image = job
    started = time.perf_counter()
    text = ENGINES[engine](image)
    elapsed = time.perf_counter() - started
    (WORK / "out" / engine / f"{image.stem}.txt").write_text(text, encoding="utf-8")
    return image.stem, elapsed


def main() -> None:
    arguments = sys.argv[1:]
    real = "--real" in arguments
    chosen = [a for a in arguments if a != "--real"] or list(ENGINES)
    images = REAL if real else IMAGES
    for engine in chosen:
        (WORK / "out" / engine).mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        workers = int(os.environ.get("BENCH_WORKERS", "4"))
        with ProcessPoolExecutor(max_workers=workers) as pool:
            timings = dict(pool.map(work, [(engine, image) for image in images]))
        name = "timings-real.json" if real else "timings.json"
        (WORK / "out" / engine / name).write_text(json.dumps(timings, indent=1))
        print(f"{engine}: {len(timings)} images in {time.perf_counter() - started:.0f} s")


if __name__ == "__main__":
    main()
