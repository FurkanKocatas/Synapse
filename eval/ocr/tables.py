"""Page clean-up before OCR for table pages (docs/benchmarks/ocr.md, "Table pages").

Measured as two engines (run.py): "-invert" inverts dark table cells only, "-tables" also
removes table rules. Not in the product: on the benchmark the gain is small and uneven (see the
report).

- ``invert_dark_cells``: a filled dark area (a table's header cells, white text on black) is
  inverted and its background scaled to white, so its text is black on white like the rest of
  the page. Left light grey, Tesseract's layout analysis takes the cell for a picture.
- ``remove_lines``: straight lines longer than half an inch and at most a thirtieth of an inch
  thick (table rules) are painted white.

Sizes are in inches, from the image's width taken as A4 paper, so any resolution works.
"""

import cv2
import numpy as np
from numpy.typing import NDArray

Grey = NDArray[np.uint8]

A4_WIDTH_INCHES = 8.27
DARK = 110  # grey level below which a pixel is ink or a dark fill
STROKE_INCHES = 0.04  # wider than any text stroke: an area this thick in both directions is a fill
FILL_HOLES_INCHES = 0.25  # closes the text inside a dark cell so the whole cell is one area
MIN_AREA_INCHES2 = 0.05
# Share of an area that must be dark: a filled cell with its text is mostly dark, while a large
# bold heading, whose letters the steps above also merge into one area, is about half paper.
DARK_SHARE = 0.6
LINE_INCHES = 0.5
LINE_THICKNESS_INCHES = 0.03  # a rule is at most this thick; a thicker dark band is a fill


def dpi(grey: Grey) -> float:
    return float(grey.shape[1]) / A4_WIDTH_INCHES


def _size(inches: float, per_inch: float, least: int) -> int:
    """A kernel size in pixels, odd: OpenCV anchors an even kernel off centre, and an opening
    with it shifts its result by a pixel."""
    return max(least, round(inches * per_inch)) | 1


def _open(image: Grey, rows: int, columns: int) -> Grey:
    kernel = np.ones((rows, columns), np.uint8)
    return np.asarray(cv2.morphologyEx(image, cv2.MORPH_OPEN, kernel), dtype=np.uint8)


def invert_dark_cells(grey: Grey) -> Grey:
    per_inch = dpi(grey)
    dark = (grey < DARK).astype(np.uint8)
    stroke = _size(STROKE_INCHES, per_inch, 3)
    fills = _open(dark, stroke, stroke)
    holes = _size(FILL_HOLES_INCHES, per_inch, 3)
    fills = np.asarray(
        cv2.morphologyEx(fills, cv2.MORPH_CLOSE, np.ones((holes, holes), np.uint8)),
        dtype=np.uint8,
    )
    count, labels, stats, _ = cv2.connectedComponentsWithStats(fills, connectivity=8)
    out = grey.copy()
    min_area = MIN_AREA_INCHES2 * per_inch * per_inch
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        if area < min_area:
            continue
        # The area itself, not its bounding box: dark cells next to white ones form one area
        # whose box covers the whole table.
        box = (slice(y, y + h), slice(x, x + w))
        region = labels[box] == index
        if dark[box][region].mean() >= DARK_SHARE:
            out[box][region] = _stretch(255 - grey[box][region])
    return out


def _stretch(values: Grey) -> Grey:
    """An inverted cell's grey background to white: left light grey, Tesseract's layout
    analysis takes the cell for a picture and skips its text. The median is the background
    whatever share the text takes, so it is scaled to white and everything with it."""
    background = max(1.0, float(np.median(values)))
    scaled = values.astype(np.float32) * 255 / background
    return np.asarray(np.clip(scaled, 0, 255), dtype=np.uint8)


def remove_lines(grey: Grey) -> Grey:
    length = _size(LINE_INCHES, dpi(grey), 11)
    # One pixel thicker than a rule: an opening that keeps anything this thick keeps no rule.
    thick = _size(LINE_THICKNESS_INCHES, dpi(grey), 1) + 2
    ink = (grey < DARK).astype(np.uint8)
    horizontal = _open(ink, 1, length)
    vertical = _open(ink, length, 1)
    # Long and thin only: a dark band thicker than a rule (a filled cell that was not inverted,
    # a photo) is left alone, or its white text would be erased with it.
    horizontal &= 1 - _open(horizontal, thick, 1)
    vertical &= 1 - _open(vertical, 1, thick)
    lines = cv2.dilate(horizontal | vertical, np.ones((3, 3), np.uint8))
    out = grey.copy()
    out[lines > 0] = 255
    return out


def clean(grey: Grey, *, invert: bool = True, lines: bool = True) -> Grey:
    if invert:
        grey = invert_dark_cells(grey)
    if lines:
        grey = remove_lines(grey)
    return grey
