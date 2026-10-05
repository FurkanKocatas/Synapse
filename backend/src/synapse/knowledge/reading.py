"""Reading order of a page's text lines from their boxes: rows top to bottom, left to right, and
columns one after the other when the page is set in columns (docs/benchmarks/ocr.md).

A column gutter is a vertical strip in the middle of the text that column lines (lines narrower
than most of the text width) do not cross, with column-wide lines on both sides of it. Lines that
do cross it (a title, a running head, a paragraph set across the page, a footnote) cut the page
into bands; within a band the left column is read before the right one. Each column is searched
for a gutter of its own, so three columns are found too. Grouping rows alone had merged the two
columns of 24 test pages line by line, and line-end hyphens and voting suffered with them.
"""

from collections.abc import Sequence

Box = Sequence[float]  # x0, y0, x1, y1
Line = tuple[Box, str]

MIN_LINES = 6  # fewer line boxes on a side are not a column
SIDE_SHARE = 0.2  # each side holds at least this share of the column lines
CROSSING_SHARE = 0.1  # at most this share of the column lines may cross the gutter
FULL_LINES = 0.7  # a column's lines are mostly as wide as the column (median width)
NARROW = 0.6  # lines narrower than this share of the text width can belong to a column
STEPS = 100  # gutter positions tried across the middle half of the text


def rows(items: Sequence[Line]) -> list[str]:
    """Lines grouped into rows by vertical centre, each row read left to right."""
    ordered = sorted(((b[1] + b[3]) / 2, b[0], b[3] - b[1], t) for b, t in items if t)
    out: list[list[tuple[float, str]]] = []
    centre: float | None = None
    for y, x, height, text in ordered:
        if centre is None or y - centre > height / 2:
            out.append([])
            centre = y
        out[-1].append((x, text))
    return [" ".join(t for _, t in sorted(row)) for row in out]


def gutter(boxes: Sequence[Box]) -> float | None:
    """The x of a column gutter, or None when the lines do not stand in columns."""
    if len(boxes) < 2 * MIN_LINES:
        return None
    x0, x1 = min(b[0] for b in boxes), max(b[2] for b in boxes)
    width = x1 - x0
    narrow = [b for b in boxes if b[2] - b[0] < NARROW * width]
    best: tuple[tuple[int, int], float] | None = None
    for i in range(STEPS + 1):
        x = x0 + width * (0.25 + 0.5 * i / STEPS)
        crossing = sum(1 for b in narrow if b[0] < x < b[2])
        left = [b[2] - b[0] for b in narrow if b[2] <= x]
        right = [b[2] - b[0] for b in narrow if b[0] >= x]
        least = max(MIN_LINES, SIDE_SHARE * len(narrow))
        if crossing > CROSSING_SHARE * len(narrow) or min(len(left), len(right)) < least:
            continue
        if median(left) < FULL_LINES * (x - x0) or median(right) < FULL_LINES * (x1 - x):
            continue  # short pieces side by side: a table or a form, read row by row
        rank = (crossing, -min(len(left), len(right)))
        if best is None or rank < best[0]:
            best = (rank, x)
    return None if best is None else best[1]


def median(values: list[float]) -> float:
    values = sorted(values)
    return values[len(values) // 2]


def reading_order(lines: Sequence[Line]) -> list[str]:
    """The page's lines of text in reading order."""
    items = [(b, t) for b, t in lines if t]
    x = gutter([b for b, _ in items])
    if x is None:
        return rows(items)
    out: list[str] = []
    band: list[Line] = []

    def flush() -> None:
        out.extend(reading_order([(b, t) for b, t in band if b[2] <= x]))
        out.extend(reading_order([(b, t) for b, t in band if b[2] > x]))
        band.clear()

    for b, t in sorted(items, key=lambda item: (item[0][1] + item[0][3]) / 2):
        if b[0] < x < b[2]:  # crosses the gutter: ends the band above it
            flush()
            out.append(t)
        else:
            band.append((b, t))
    flush()
    return out
