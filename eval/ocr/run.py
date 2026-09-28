"""Run every OCR engine over the benchmark images (inside the synapse-ocr-bench container).

    docker run --rm -v "$PWD/eval/ocr:/bench" synapse-ocr-bench [--real] [ENGINE ...]

``--real`` runs only the real scans in /bench/work/real/ (hand-verified truths in real/).

Reads /bench/work/images/*.png, writes /bench/work/out/<engine>/<image>.txt and timings in
/bench/work/out/<engine>/timings.json. Each image is OCR'd by one process with one thread, so the
time per page is comparable across engines; pages run four at a time.
"""

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from multiprocessing import Pool
from pathlib import Path

os.environ["OMP_THREAD_LIMIT"] = "1"  # Tesseract: one thread per page

WORK = Path("/bench/work")
IMAGES = sorted((WORK / "images").glob("*.png"))
REAL = sorted((WORK / "real").glob("*.png"))


def tesseract(
    tessdata: str | None, languages: str, *, psm: int = 3, upscale_below_dpi: int = 0
) -> Callable[[Path], str]:
    """``upscale_below_dpi``: images whose width suggests less than this resolution on A4 are
    enlarged to it first (Tesseract is trained on text about 300 dpi high)."""

    def run(image: Path) -> str:
        source = image
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


_rapid = None


def rapidocr(image: Path) -> str:
    global _rapid
    if _rapid is None:
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

        # The Latin recogniser exists for PP-OCRv5, in the mobile size only.
        _rapid = RapidOCR(
            params={
                "Rec.lang_type": LangRec.LATIN,
                "Rec.ocr_version": OCRVersion.PPOCRV5,
                "Rec.model_type": ModelType.MOBILE,
                "Global.log_level": "error",
            }
        )
    output = _rapid(str(image))
    return "\n".join(output.txts or ())


def hybrid_engine(image: Path) -> str:
    import hybrid

    return hybrid.recognize(image, "/models/best", "tur+eng")


ENGINES: dict[str, Callable[[Path], str]] = {
    "tesseract-debian-tur": tesseract(None, "tur"),
    "tesseract-fast-tur": tesseract("/models/fast", "tur"),
    "tesseract-best-tur": tesseract("/models/best", "tur"),
    "tesseract-best-tur+eng": tesseract("/models/best", "tur+eng"),
    "rapidocr-latin": rapidocr,
    "tesseract-best-tur+eng-psm4": tesseract("/models/best", "tur+eng", psm=4),
    "tesseract-best-tur+eng-psm6": tesseract("/models/best", "tur+eng", psm=6),
    "tesseract-best-tur+eng-up300": tesseract("/models/best", "tur+eng", upscale_below_dpi=300),
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
        with Pool(4) as pool:
            timings = dict(pool.map(work, [(engine, image) for image in images], chunksize=1))
        name = "timings-real.json" if real else "timings.json"
        (WORK / "out" / engine / name).write_text(json.dumps(timings, indent=1))
        print(f"{engine}: {len(timings)} images in {time.perf_counter() - started:.0f} s")


if __name__ == "__main__":
    main()
