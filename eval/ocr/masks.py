"""Where a born-digital page's text layer and what the page shows part ways.

The OCR benchmark's truth is the page's text layer, and it differs from the page twice:

- An image on the page (a map with its place names, a logo, a chart saved as a picture) shows
  words the text layer lacks, so an engine that reads them correctly is counted wrong for every
  one. ``unread_regions``: images with no text-layer character over them, to be blanked before
  the page is rendered. An image under text (a scanned page with its recognised text, a
  letterhead behind a letter) is left alone: its words are in the truth. An image drawn inside a
  form object has bounds in the form's own space, so the top-level form stands for it.
- Text that leaves no ink (drawn invisibly, white on the white page as a signature block's
  hidden copy is, or placed beyond the page's edge) is in the text layer and nowhere on the
  page, so an engine is counted wrong for not reading it. ``seen_text``: the text layer without
  the characters whose box is one flat colour on the rendered page, or off it. Text drawn
  invisibly over a scan keeps the scan's pixels in its boxes, so an OCR'd scan's text stays.

prepare.py --masked writes the benchmark both ways corrected, so the masked set measures the
engines against what the page shows.
"""

import math
from collections.abc import Iterable, Sequence
from typing import Protocol, cast

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from PIL import Image

# left, bottom, right, top in PDF points, origin at the page's bottom left
Box = tuple[float, float, float, float]
# left, top, right, bottom in pixels, origin at the image's top left
PixelBox = tuple[int, int, int, int]

IMAGE = pdfium_c.FPDF_PAGEOBJ_IMAGE
FORM = pdfium_c.FPDF_PAGEOBJ_FORM
# A character's box whose grey values span less than this holds no glyph: a glyph's edge against
# what is under it spans far more, even light grey on white.
INK = 16
# Points a character's box is widened by before it is looked at: pdfium's box of a full stop, a
# hyphen or an l can lie wholly inside the glyph, one flat black; the widened box takes in its edge.
EDGE = 1.0


class PageObject(Protocol):
    type: int
    level: int

    def get_bounds(self) -> Box: ...


def holds_a_character(box: Box, chars: Sequence[Box]) -> bool:
    left, bottom, right, top = box
    return any(
        left <= (c[0] + c[2]) / 2 <= right and bottom <= (c[1] + c[3]) / 2 <= top for c in chars
    )


def image_boxes(objects: Iterable[PageObject]) -> list[Box]:
    """Top-level images, and top-level forms that draw an image, in page space.

    ``objects`` in document order, each form followed by what it holds (one level deeper).
    """
    boxes: list[Box] = []
    form: Box | None = None
    form_draws_image = False
    for obj in objects:
        if obj.level == 0:
            if form is not None and form_draws_image:
                boxes.append(form)
            form = obj.get_bounds() if obj.type == FORM else None
            form_draws_image = False
            if obj.type == IMAGE:
                boxes.append(obj.get_bounds())
        elif obj.type == IMAGE and form is not None:
            form_draws_image = True
    if form is not None and form_draws_image:
        boxes.append(form)
    return boxes


def to_pixels(box: Box, page_height: float, scale: float) -> PixelBox:
    left, bottom, right, top = box
    return (
        math.floor(left * scale),
        math.floor((page_height - top) * scale),
        math.ceil(right * scale),
        math.ceil((page_height - bottom) * scale),
    )


def unread_regions(page: pdfium.PdfPage, scale: float) -> list[PixelBox]:
    """The page's images with no text-layer character over them, in pixels at ``scale``."""
    text = page.get_textpage()
    chars = [text.get_charbox(i) for i in range(text.count_chars())]
    chars = [c for c in chars if c[2] > c[0] and c[3] > c[1]]
    _, height = page.get_size()
    boxes = image_boxes(page.get_objects(max_depth=15))
    return [to_pixels(b, height, scale) for b in boxes if not holds_a_character(b, chars)]


def widened(box: Box) -> Box:
    left, bottom, right, top = box
    return (left - EDGE, bottom - EDGE, right + EDGE, top + EDGE)


def shows_ink(grey: Image.Image, box: PixelBox) -> bool:
    """Whether ``box`` on the rendered page ``grey`` holds anything but one flat colour."""
    left, top, right, bottom = box
    left, top = max(left, 0), max(top, 0)
    right, bottom = min(right, grey.width), min(bottom, grey.height)
    if right <= left or bottom <= top:  # off the page
        return False
    # one band, so the lowest and the highest grey value
    low, high = cast(tuple[int, int], grey.crop((left, top, right, bottom)).getextrema())
    return bool(high - low >= INK)


def unseen_chars(page: pdfium.PdfPage, grey: Image.Image, scale: float) -> list[int]:
    """Indices of the text layer's characters that leave no ink on ``grey``, the page rendered
    at ``scale``."""
    text = page.get_textpage()
    _, height = page.get_size()
    found = []
    for index in range(text.count_chars()):
        box = text.get_charbox(index)
        if box[2] <= box[0] or box[3] <= box[1]:  # a space or a line break: no glyph either way
            continue
        if not shows_ink(grey, to_pixels(widened(box), height, scale)):
            found.append(index)
    return found


def seen_text(page: pdfium.PdfPage, grey: Image.Image, scale: float) -> str:
    """The text layer as ``get_text_range`` gives it, its unseen characters made spaces."""
    text = page.get_textpage()
    full: str = text.get_text_range()
    hidden = set(unseen_chars(page, grey, scale))
    if not hidden:
        return full
    count = text.count_chars()
    # One string index per character, unless a character outside the BMP takes two.
    chars = list(full) if len(full) == count else [text.get_text_range(i, 1) for i in range(count)]
    # a space, tab or line break keeps its place: it was never ink
    return "".join(" " if i in hidden and not c.isspace() else c for i, c in enumerate(chars))
