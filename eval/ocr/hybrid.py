"""Hybrid OCR: RapidOCR finds the text lines, Tesseract reads them.

RapidOCR's detector finds lines reliably, including table cells and white text on dark cells,
but its Latin recogniser often drops Turkish letters (ı -> i, ş -> s). Tesseract reads Turkish
well but segments tables poorly. So: detect with RapidOCR, cut each line out (inverting dark
ones), stack the lines into one tall image with white gaps, and let Tesseract read that image in
one call, which avoids loading its model once per line.

Used by run.py as the "hybrid" engines.
"""

import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps

GAP = 24
PAD = 4
DARK = 110  # mean grey level below which a line is white text on a dark background

_detector = None


def detector(engine_params: dict[str, Any] | None = None):  # type: ignore[no-untyped-def]
    """``engine_params``: extra RapidOCR settings, applied when the detector is first created."""
    global _detector
    if _detector is None:
        from rapidocr import RapidOCR

        _detector = RapidOCR(params={"Global.log_level": "error", **(engine_params or {})})
    return _detector


def line_boxes(
    image: Path, engine_params: dict[str, Any] | None = None
) -> list[tuple[int, int, int, int]]:
    result = detector(engine_params)(str(image), use_det=True, use_cls=False, use_rec=False)
    boxes = []
    for quad in result.boxes if result.boxes is not None else []:
        xs, ys = quad[:, 0], quad[:, 1]
        boxes.append((int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())))
    # Reading order: top to bottom, then left to right within a row.
    boxes.sort(key=lambda b: (round(b[1] / 20), b[0]))
    return boxes


def stacked_lines(image: Path, engine_params: dict[str, Any] | None = None) -> Image.Image | None:
    page = Image.open(image).convert("L")
    crops = []
    for x0, y0, x1, y1 in line_boxes(image, engine_params):
        crop = page.crop((max(0, x0 - PAD), max(0, y0 - PAD), x1 + PAD, y1 + PAD))
        if np.asarray(crop).mean() < DARK:
            crop = ImageOps.invert(crop)
        crops.append(crop)
    if not crops:
        return None
    width = max(c.width for c in crops) + 2 * GAP
    height = sum(c.height + GAP for c in crops) + GAP
    sheet = Image.new("L", (width, height), 255)
    y = GAP
    for crop in crops:
        sheet.paste(crop, (GAP, y))
        y += crop.height + GAP
    return sheet


def recognize(
    image: Path, tessdata: str, languages: str, engine_params: dict[str, Any] | None = None
) -> str:
    sheet = stacked_lines(image, engine_params)
    if sheet is None:
        return ""
    with tempfile.NamedTemporaryFile(suffix=".png") as handle:
        sheet.save(handle.name)
        command = [
            "tesseract",
            handle.name,
            "-",
            "-l",
            languages,
            "--oem",
            "1",
            "--psm",
            "4",
            "--tessdata-dir",
            tessdata,
        ]
        text = subprocess.run(command, capture_output=True, text=True, check=True).stdout
    return "\n".join(line for line in text.splitlines() if looks_like_text(line))


MIN_ALNUM_SHARE = 0.5
MIN_WORD = 3


def looks_like_text(line: str) -> bool:
    """Drops lines read from table borders and other detections that are not text ("ges ep")."""
    visible = [ch for ch in line if not ch.isspace()]
    if not visible:
        return False
    alnum = sum(ch.isalnum() for ch in visible)
    has_word = any(len(w.strip(".,;:()")) >= MIN_WORD for w in line.split())
    has_number = any(ch.isdigit() for ch in line)
    return alnum / len(visible) >= MIN_ALNUM_SHARE and (has_word or has_number)
