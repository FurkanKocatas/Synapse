"""PP-OCRv6 on onnxruntime: a page's text from its text lines, each read with the character
language model and put in reading order (docs/benchmarks/ocr.md), in a child process.

The models are PaddleOCR's PP-OCRv6 medium detector and a recogniser fine-tuned for Turkish,
exported with paddle2onnx. The steps below are PaddleOCR's own (paddlex 3.7: DetResizeForTest,
NormalizeImage, DBPostProcess, CropByPolys, OCRReisizeNormImg), so the exported models read as
they do under Paddle: on 200 test pages the boxes came out in the same order, a few of them one or
two pixels apart, and 99.9% of the recogniser's likeliest characters were the same.

The model directory (``ocr_ppocr_dir``) holds detection.onnx, recognition.onnx, characters.json
(the recogniser's character list, index 0 the CTC blank), charlm.npz (synapse.knowledge.charlm)
and, for the second reading of identifiers, second.onnx and second.json (PP-OCRv5 Latin mobile).

The child process is arranged as RapidOCR's (rapid.py): onnxruntime holds on to memory for the
input shapes it has seen, and a crash in native code must not take the worker with it.
"""

import json
import math
import multiprocessing
import threading
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from synapse.knowledge.ocr import OCR_TIMEOUT_SECONDS, OcrError, PageReading, two_readings

PAGES_PER_CHILD = 25

# PaddleOCR's OCR pipeline settings for PP-OCRv6 (paddlex configs/pipelines/OCR.yaml), except
# the long side: the pipeline's 4000 lets the detector take 2.7 GB on a 300 dpi page. At 2500
# it takes 1.5 GB and reads as well (corpus benchmark clean 98.25 -> 98.33, scan 98.27 -> 98.29;
# old books 94.73 -> 94.66, within noise). Much smaller is not better: the detection module's
# own default (long side 960) lost small print on 150 dpi scans.
LIMIT_SIDE, MAX_SIDE = 64, 2500
THRESH, BOX_THRESH, UNCLIP = 0.3, 0.6, 1.5
MAX_CANDIDATES, MIN_SIZE = 1000, 3
MEAN, STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)
REC_HEIGHT, REC_MIN_WIDTH, REC_MAX_WIDTH = 48, 320, 3200
MIN_SIDE = 4  # pixels; a thinner detection is a speck, not text
UPRIGHT = 1.5  # a crop this many times taller than wide is a vertical line, turned to read

DARK, INK_SHARE = 128, 0.01  # a page with more than 1% of pixels darker than mid-grey has ink
FEW_LINES = 3  # fewer lines than this on a page with ink: read it again
RUNS = 2  # tries for a model output that is not finite

Quad = NDArray[np.int16]  # 4 x 2, clockwise from the top left
# a line's upright box (x0, y0, x1, y1) and its frame-by-frame character distributions
Line = tuple[tuple[int, int, int, int], NDArray[np.float32]]
# a line's upright box and its crop, straightened
Detected = tuple[tuple[int, int, int, int], NDArray[np.uint8]]


# onnxruntime, OpenCV and pyclipper are imported where they are used: the API process imports
# this package too and needs none of them.


def _session(model: Path, threads: int) -> Any:
    import onnxruntime as ort  # noqa: PLC0415  (see above)

    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.log_severity_level = 3
    # Every page and line has its own size: an arena keeps the largest it has seen (4.6 GB after
    # a few pages), and memory patterns are made for fixed shapes.
    options.enable_cpu_mem_arena = False
    options.enable_mem_pattern = False
    return ort.InferenceSession(str(model), options, providers=["CPUExecutionProvider"])


def detection_size(height: int, width: int) -> tuple[int, int]:
    """The size the detector reads the page at: multiples of 32, the short side at least 64,
    the long side at most MAX_SIDE (DetResizeForTest, limit type "min")."""
    ratio = LIMIT_SIDE / min(height, width) if min(height, width) < LIMIT_SIDE else 1.0
    h, w = int(height * ratio), int(width * ratio)
    if max(h, w) > MAX_SIDE:
        ratio = MAX_SIDE / max(h, w)
        h, w = int(h * ratio), int(w * ratio)
    return max(round(h / 32) * 32, 32), max(round(w / 32) * 32, 32)


def mini_box(contour: NDArray[Any]) -> tuple[NDArray[np.float32], float]:
    """The contour's minimum-area rectangle, its corners clockwise from the top left, and its
    short side."""
    import cv2  # noqa: PLC0415  (see above)

    rect = cv2.minAreaRect(contour)
    points = sorted(cv2.boxPoints(rect), key=lambda p: float(p[0]))
    a, d = (0, 1) if points[1][1] > points[0][1] else (1, 0)
    b, c = (2, 3) if points[3][1] > points[2][1] else (3, 2)
    return np.array([points[a], points[b], points[c], points[d]], dtype=np.float32), min(rect[1])


def box_score(pred: NDArray[np.float32], box: NDArray[np.float32]) -> float:
    """The mean text probability inside the box (DBPostProcess, score mode "fast")."""
    import cv2  # noqa: PLC0415  (see above)

    h, w = pred.shape
    x0 = max(0, min(math.floor(box[:, 0].min()), w - 1))
    x1 = max(0, min(math.ceil(box[:, 0].max()), w - 1))
    y0 = max(0, min(math.floor(box[:, 1].min()), h - 1))
    y1 = max(0, min(math.ceil(box[:, 1].max()), h - 1))
    mask = np.zeros((y1 - y0 + 1, x1 - x0 + 1), dtype=np.uint8)
    shifted = box.copy()
    shifted[:, 0] -= x0
    shifted[:, 1] -= y0
    cv2.fillPoly(mask, [shifted.reshape(-1, 2).astype(np.int32)], 1)
    return float(cv2.mean(pred[y0 : y1 + 1, x0 : x1 + 1], mask)[0])


def unclip(box: NDArray[np.float32]) -> NDArray[Any]:
    """The box grown by area * ratio / perimeter: the detector marks a line's core only."""
    import cv2  # noqa: PLC0415  (see above)
    import pyclipper  # noqa: PLC0415

    distance = cv2.contourArea(box) * UNCLIP / cv2.arcLength(box, closed=True)
    offset = pyclipper.PyclipperOffset()
    offset.AddPath(box, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
    expanded = offset.Execute(distance)
    return np.array(expanded[0] if len(expanded) == 1 else expanded)


def boxes_from_map(pred: NDArray[np.float32], width: int, height: int) -> list[Quad]:
    """Text line quadrilaterals in page coordinates from the detector's probability map."""
    import cv2  # noqa: PLC0415  (see above)

    sx, sy = width / pred.shape[1], height / pred.shape[0]
    bitmap = ((pred > THRESH) * 255).astype(np.uint8)
    contours, _ = cv2.findContours(bitmap, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    quads = []
    for contour in contours[:MAX_CANDIDATES]:
        points, side = mini_box(contour)
        if side < MIN_SIZE or box_score(pred, points.reshape(-1, 2)) < BOX_THRESH:
            continue
        box, side = mini_box(unclip(points).reshape(-1, 1, 2))
        if side < MIN_SIZE + 2:
            continue
        box[:, 0] = np.clip(np.round(box[:, 0] * sx), 0, width)
        box[:, 1] = np.clip(np.round(box[:, 1] * sy), 0, height)
        quads.append(box.astype(np.int16))
    return quads


def crop_line(page: NDArray[np.uint8], quad: Quad) -> NDArray[np.uint8]:
    """The line cut along its minimum-area rectangle and straightened (CropByPolys, "quad")."""
    import cv2  # noqa: PLC0415  (see above)

    points, _ = mini_box(np.asarray(quad).astype(np.int32))
    w = int(max(np.linalg.norm(points[0] - points[1]), np.linalg.norm(points[2] - points[3])))
    h = int(max(np.linalg.norm(points[0] - points[3]), np.linalg.norm(points[1] - points[2])))
    target = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
    crop = cv2.warpPerspective(
        page,
        cv2.getPerspectiveTransform(points, target),
        (w, h),
        borderMode=cv2.BORDER_REPLICATE,
        flags=cv2.INTER_CUBIC,
    )
    if crop.shape[0] / crop.shape[1] >= UPRIGHT:
        crop = np.rot90(crop)
    return np.ascontiguousarray(crop)


def recognition_input(crop: NDArray[np.uint8]) -> NDArray[np.float32]:
    """The line at height 48 and its own aspect ratio (at least 320 wide, at most 3200),
    scaled to [-1, 1] and padded on the right (OCRReisizeNormImg)."""
    import cv2  # noqa: PLC0415  (see above)

    h, w = crop.shape[:2]
    # the same expressions as paddlex, so rounding lands on the same pixel
    width = int(REC_HEIGHT * max(REC_MIN_WIDTH / REC_HEIGHT, w * 1.0 / h))
    if width > REC_MAX_WIDTH:
        resized, used, width = (
            cv2.resize(crop, (REC_MAX_WIDTH, REC_HEIGHT)),
            REC_MAX_WIDTH,
            REC_MAX_WIDTH,
        )
    else:
        used = min(width, math.ceil(REC_HEIGHT * (w / float(h))))
        resized = cv2.resize(crop, (used, REC_HEIGHT))
    x = np.zeros((3, REC_HEIGHT, width), dtype=np.float32)
    x[:, :, :used] = (resized.astype(np.float32).transpose(2, 0, 1) / 255 - 0.5) / 0.5
    return x[None]


class NotFiniteError(RuntimeError):
    """A model gave NaN or infinite values twice for the same input."""


def finite_run(session: Any, x: NDArray[np.float32]) -> NDArray[np.float32]:
    """The model's output for ``x``, run again if it is not finite. Under memory pressure from
    other work the detector once returned a map of NaN for a page it reads normally otherwise
    (no line found, an empty page): a second run, or an error the reader reports, never an
    empty text taken for the page's."""
    for _ in range(RUNS):
        out: NDArray[np.float32] = session.run(None, {"x": x})[0]
        if np.isfinite(out).all():
            return out
    raise NotFiniteError("the model gave values that are not finite")


@dataclass
class Models:
    detector: Any
    recognizer: Any
    characters: list[str]
    lm: Any
    # A second recogniser (second.onnx, second.json) reads the same lines once more: the second
    # reading of identifiers that RapidOCR gives beside Tesseract, without a second detector.
    second: Any | None = None
    second_characters: list[str] | None = None

    @classmethod
    def load(cls, directory: Path, threads: int) -> Models:
        from synapse.knowledge.charlm import CharLM  # noqa: PLC0415  (numpy only, still lazy)

        def characters(name: str) -> list[str]:
            return list(json.loads((directory / name).read_text(encoding="utf-8")))

        has_second = (directory / "second.onnx").exists()
        return cls(
            detector=_session(directory / "detection.onnx", threads),
            recognizer=_session(directory / "recognition.onnx", threads),
            characters=characters("characters.json"),
            lm=CharLM.load(directory / "charlm.npz"),
            second=_session(directory / "second.onnx", threads) if has_second else None,
            second_characters=characters("second.json") if has_second else None,
        )

    def detect(self, page: NDArray[np.uint8]) -> list[Detected]:
        """Each text line's box and its crop, straightened, for a BGR page."""
        import cv2  # noqa: PLC0415  (see above)

        height, width = page.shape[:2]
        rh, rw = detection_size(height, width)
        resized = page if (rh, rw) == (height, width) else cv2.resize(page, (rw, rh))
        planes = [
            resized[:, :, c].astype(np.float32) * (1 / 255 / STD[c]) - MEAN[c] / STD[c]
            for c in range(3)
        ]
        pred = finite_run(self.detector, np.stack(planes)[None])[0, 0]
        out = []
        for quad in boxes_from_map(pred, width, height):
            xs, ys = quad[:, 0].astype(float), quad[:, 1].astype(float)
            box = (
                max(0, int(xs.min())),
                max(0, int(ys.min())),
                int(xs.max()) + 1,
                int(ys.max()) + 1,
            )
            if box[2] - box[0] < MIN_SIDE or box[3] - box[1] < MIN_SIDE:
                continue
            out.append((box, crop_line(page, quad)))
        return out

    def recognize(self, crop: NDArray[np.uint8], *, second: bool = False) -> NDArray[np.float32]:
        """A line's frame-by-frame character distributions, by the recogniser or the second."""
        session = self.second if second else self.recognizer
        probs: NDArray[np.float32] = finite_run(session, recognition_input(crop))[0]
        return probs

    def lines(self, page: NDArray[np.uint8]) -> list[Line]:
        """Each text line's box and frame-by-frame character distributions, for a BGR page."""
        return [(box, self.recognize(crop)) for box, crop in self.detect(page)]


def inked(page: NDArray[np.uint8]) -> bool:
    """Whether more than INK_SHARE of the page is dark: not a blank page."""
    return float((page.mean(axis=2) < DARK).mean()) > INK_SHARE


def detected(models: Models, page: NDArray[np.uint8]) -> list[Detected]:
    """The page's lines; a page with ink and next to no line is read a second time. In long runs
    beside other heavy work, five of 312 test pages came back with no line or a few words, and
    read normally when read again (once the detector's map was all NaN: see finite_run)."""
    found = models.detect(page)
    if len(found) < FEW_LINES and inked(page):
        found = models.detect(page)
    return found


# The child's models, loaded by its first page and kept for the pages after it.
_models: dict[tuple[str, int], Models] = {}


def _prepared(image: str, directory: str, threads: int) -> tuple[Models, NDArray[np.uint8]]:
    from PIL import Image  # noqa: PLC0415  (see above)

    if (directory, threads) not in _models:
        _models[directory, threads] = Models.load(Path(directory), threads)
    with Image.open(image) as source:
        page = np.asarray(source.convert("RGB"))[:, :, ::-1].copy()  # BGR, as the models read
    return _models[directory, threads], page


def _text(models: Models, found: list[Detected], *, second: bool = False) -> str:
    """The lines read by one recogniser with the language model, in reading order."""
    from synapse.knowledge.ctc import LanguageScore, Search, read_line  # noqa: PLC0415
    from synapse.knowledge.reading import reading_order  # noqa: PLC0415

    characters = models.second_characters if second else models.characters
    if characters is None:
        raise OcrError("the model directory has no second recogniser (second.onnx)")
    score, search = LanguageScore(models.lm), Search()
    lines = [
        (box, read_line(models.recognize(crop, second=second), characters, score, search))
        for box, crop in found
    ]
    return "\n".join(reading_order(lines))


def read_page(image: str, directory: str, threads: int) -> str:  # runs in the child process
    models, page = _prepared(image, directory, threads)
    return _text(models, detected(models, page))


def read_page_twice(image: str, directory: str, threads: int) -> tuple[str, str]:  # in the child
    """The page's text and the second recogniser's reading of the same lines."""
    models, page = _prepared(image, directory, threads)
    found = detected(models, page)
    return _text(models, found), _text(models, found, second=True)


class _Child:
    """The engine's child process: spawned, replaced after PAGES_PER_CHILD pages, killed when a
    page takes too long or the process dies; one page at a time."""

    def __init__(self, timeout: float) -> None:
        self._timeout = timeout
        self._lock = threading.Lock()
        self._pool: ProcessPoolExecutor | None = None

    def run(self, work: Callable[..., Any], *args: object) -> Any:
        with self._lock:
            if self._pool is None:
                self._pool = ProcessPoolExecutor(
                    max_workers=1,
                    # A fresh interpreter: forking a threaded worker is unsafe.
                    mp_context=multiprocessing.get_context("spawn"),
                    max_tasks_per_child=PAGES_PER_CHILD,
                )
            future = self._pool.submit(work, *args)
            try:
                return future.result(timeout=self._timeout)
            except (BrokenProcessPool, TimeoutError) as error:
                self._discard()
                raise OcrError(f"ppocr failed: {type(error).__name__}") from error
            except Exception as error:
                # Raised inside the models or the image library; the child is still fine.
                raise OcrError(f"ppocr failed: {type(error).__name__}") from error

    def close(self) -> None:
        with self._lock:
            if self._pool is not None:
                self._pool.shutdown(wait=True, cancel_futures=True)
                self._pool = None

    def _discard(self) -> None:
        # The child may still be running the page that timed out.
        if self._pool is not None:
            self._pool.kill_workers()
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None


class PpOcrEngine:
    """The text engine alone (TextEngine): PP-OCRv6 with the language model."""

    name = "ppocrv6-tr-lm"

    def __init__(
        self,
        directory: Path,
        threads: int = 1,
        *,
        read: Callable[[str, str, int], str] = read_page,
        timeout: float = OCR_TIMEOUT_SECONDS,
    ) -> None:
        """``read`` runs in the child; it must be a module-level function (tests replace it to
        exercise crashes and timeouts without the models)."""
        self._directory = directory
        self._threads = threads
        self._read = read
        self._child = _Child(timeout)

    def recognize(self, image: Path) -> str:
        text: str = self._child.run(self._read, str(image), str(self._directory), self._threads)
        return text

    def close(self) -> None:
        self._child.close()


class PpOcrReader:
    """The page reader (PageReader): PP-OCRv6's text, and the second recogniser's reading of the
    same lines for a second reading of the identifiers, as RapidOCR gives one beside Tesseract
    (TwoEngineReader) but without a second detector or a second child process: the two children
    did not fit the worker's memory together."""

    name = "ppocrv6-tr-lm+latin"

    def __init__(
        self,
        directory: Path,
        threads: int = 1,
        *,
        read: Callable[[str, str, int], tuple[str, str]] = read_page_twice,
        timeout: float = OCR_TIMEOUT_SECONDS,
    ) -> None:
        self._directory = directory
        self._threads = threads
        self._read = read
        self._child = _Child(timeout)

    def read(self, image: Path) -> PageReading:
        text, second = self._child.run(self._read, str(image), str(self._directory), self._threads)
        return two_readings(text, second, self.name)

    def close(self) -> None:
        self._child.close()
