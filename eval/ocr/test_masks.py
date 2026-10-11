"""The masked benchmark's corrections (masks.py): images no text-layer character lies on, and
text that leaves no ink on the page.

uv run --directory backend pytest ../eval/ocr/test_masks.py
"""

# ruff: noqa: S101  (pytest asserts)

import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))

from masks import (
    FORM,
    IMAGE,
    Box,
    holds_a_character,
    image_boxes,
    shows_ink,
    to_pixels,
    widened,
)

TEXT = 1  # any object type that is neither an image nor a form


@dataclass
class Obj:
    type: int
    level: int
    bounds: Box

    def get_bounds(self) -> Box:
        return self.bounds


def test_an_image_with_a_character_over_it_holds_one() -> None:
    logo = (100.0, 700.0, 200.0, 760.0)
    assert not holds_a_character(logo, [(300.0, 700.0, 310.0, 712.0)])
    assert holds_a_character(logo, [(140.0, 720.0, 150.0, 732.0)])
    # only a character's centre counts: one that touches the edge is not over the image
    assert not holds_a_character(logo, [(195.0, 720.0, 215.0, 732.0)])


def test_top_level_images_and_forms_that_draw_one() -> None:
    objects = [
        Obj(IMAGE, 0, (10.0, 10.0, 50.0, 50.0)),
        Obj(TEXT, 0, (0.0, 0.0, 600.0, 800.0)),
        # a form whose image has bounds in the form's own space: the form stands for it
        Obj(FORM, 0, (400.0, 700.0, 500.0, 780.0)),
        Obj(IMAGE, 1, (0.0, 0.0, 72.0, 72.0)),
        # a form with text only is no region
        Obj(FORM, 0, (0.0, 0.0, 600.0, 60.0)),
        Obj(TEXT, 1, (0.0, 0.0, 100.0, 12.0)),
        # a form whose image is deeper still, the last object on the page
        Obj(FORM, 0, (20.0, 300.0, 300.0, 500.0)),
        Obj(FORM, 1, (0.0, 0.0, 10.0, 10.0)),
        Obj(IMAGE, 2, (0.0, 0.0, 5.0, 5.0)),
    ]
    assert image_boxes(objects) == [
        (10.0, 10.0, 50.0, 50.0),
        (400.0, 700.0, 500.0, 780.0),
        (20.0, 300.0, 300.0, 500.0),
    ]


def test_a_glyph_leaves_ink_where_one_flat_colour_does_not() -> None:
    page = Image.new("L", (200, 100), 255)
    draw = ImageDraw.Draw(page)
    draw.text((10, 10), "A", fill=0)  # black on white
    draw.rectangle((100, 0, 199, 99), fill=60)  # a dark banner
    draw.text((110, 10), "A", fill=255)  # white on the banner
    assert shows_ink(page, (8, 8, 24, 24))
    assert shows_ink(page, (108, 8, 124, 24))
    # white on the white page, or nothing at all: one flat colour
    assert not shows_ink(page, (40, 40, 60, 60))
    assert not shows_ink(page, (140, 40, 160, 60))
    # light grey on white still shows
    draw.text((10, 60), "A", fill=215)
    assert shows_ink(page, (8, 58, 24, 74))
    # a box off the page shows nothing
    assert not shows_ink(page, (300, 10, 320, 30))


def test_a_box_inside_its_glyph_is_widened_to_the_edge() -> None:
    # a hyphen, 10 x 1 pt, at 300 dpi on a page 100 pt high; pdfium's box lies inside it
    page = Image.new("L", (400, 400), 255)
    ImageDraw.Draw(page).rectangle(to_pixels((40.0, 50.0, 50.0, 51.0), 100.0, 300 / 72), fill=0)
    inside = (40.5, 50.2, 49.5, 50.8)
    assert not shows_ink(page, to_pixels(inside, 100.0, 300 / 72))
    assert shows_ink(page, to_pixels(widened(inside), 100.0, 300 / 72))


def test_points_become_pixels_from_the_top_left() -> None:
    # a 72 x 72 pt box at the top left of an A4 page (842 pt high), at 300 dpi
    assert to_pixels((0.0, 770.0, 72.0, 842.0), 842.0, 300 / 72) == (0, 0, 300, 300)
    # fractions round outwards, so the whole image is covered
    assert to_pixels((10.1, 100.0, 20.9, 200.5), 842.0, 1.0) == (10, 641, 21, 742)
