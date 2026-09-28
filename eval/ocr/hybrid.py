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

import numpy as np
from PIL import Image, ImageOps

GAP = 24
PAD = 4
DARK = 110  # mean grey level below which a line is white text on a dark background

_detector = None


def detector():  # type: ignore[no-untyped-def]
    global _detector
    if _detector is None:
        from rapidocr import RapidOCR

        _detector = RapidOCR(params={"Global.log_level": "error"})
    return _detector


def line_boxes(image: Path) -> list[tuple[int, int, int, int]]:
    result = detector()(str(image), use_det=True, use_cls=False, use_rec=False)
    boxes = []
    for quad in result.boxes if result.boxes is not None else []:
        xs, ys = quad[:, 0], quad[:, 1]
        boxes.append((int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())))
    # Reading order: top to bottom, then left to right within a row.
    boxes.sort(key=lambda b: (round(b[1] / 20), b[0]))
    return boxes


def stacked_lines(image: Path) -> Image.Image | None:
    page = Image.open(image).convert("L")
    crops = []
    for x0, y0, x1, y1 in line_boxes(image):
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


def recognize(image: Path, tessdata: str, languages: str) -> str:
    sheet = stacked_lines(image)
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
        return subprocess.run(command, capture_output=True, text=True, check=True).stdout
