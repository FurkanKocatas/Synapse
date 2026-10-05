"""The PP-OCRv6 engine without its models: the image steps on synthetic pages, the glue between
detector and recogniser with stand-in sessions, and the child process when it crashes, hangs or
fails. The models themselves are checked against Paddle in eval (docs/benchmarks/ocr.md)."""

import time
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

from synapse.kernel.config import Settings
from synapse.knowledge import ppocr
from synapse.knowledge.ctc import LanguageScore, Search, read_line
from synapse.knowledge.ocr import OcrError, TesseractEngine, TwoEngineReader
from synapse.worker_cli import page_reader
from tests import ppocr_children


def test_the_detector_reads_the_page_at_its_own_size_in_multiples_of_32() -> None:
    assert ppocr.detection_size(2400, 1700) == (2400, 1696)
    assert ppocr.detection_size(40, 100) == (64, 160)  # the short side is raised to 64
    assert ppocr.detection_size(5000, 3000) == (2496, 1504)  # the long side is capped at 2500


def test_a_line_is_scaled_to_height_48_and_padded_to_at_least_320() -> None:
    crop = np.full((30, 100, 3), 255, dtype=np.uint8)
    x = ppocr.recognition_input(crop)
    assert x.shape == (1, 3, 48, 320)
    assert np.allclose(x[0, :, :, :160], 1.0)  # white is 1 after scaling to [-1, 1]
    assert np.allclose(x[0, :, :, 160:], 0.0)  # the padding
    wide = ppocr.recognition_input(np.zeros((30, 3000, 3), dtype=np.uint8))
    assert wide.shape == (1, 3, 48, 3200)


def test_a_line_is_cut_out_straight_and_a_vertical_one_turned() -> None:
    page = np.zeros((200, 400, 3), dtype=np.uint8)
    page[40:80, 50:250] = 200
    quad = np.array([[50, 40], [250, 40], [250, 80], [50, 80]], dtype=np.int16)
    crop = ppocr.crop_line(page, quad)
    assert crop.shape[:2] == (40, 200)
    assert crop.mean() > 190
    tall = np.array([[10, 10], [30, 10], [30, 110], [10, 110]], dtype=np.int16)
    assert ppocr.crop_line(page, tall).shape[:2] == (20, 100)


def test_two_marked_regions_become_two_lines_in_page_coordinates() -> None:
    pred = np.zeros((100, 200), dtype=np.float32)
    pred[10:20, 20:120] = 0.9
    pred[50:62, 30:180] = 0.9
    quads = sorted(
        ppocr.boxes_from_map(pred, width=400, height=200), key=lambda q: int(q[:, 1].min())
    )
    assert len(quads) == 2
    # each box covers its core scaled by 2 to the page, grown a little (unclip), no further
    for q, (y0, y1, x0, x1) in zip(quads, [(10, 20, 20, 120), (50, 62, 30, 180)], strict=True):
        assert q[:, 1].min() <= 2 * y0 and q[:, 1].max() >= 2 * y1 - 2
        assert q[:, 0].min() <= 2 * x0 and q[:, 0].max() >= 2 * x1 - 2
        assert q[:, 1].max() - q[:, 1].min() < 2 * (y1 - y0) + 40
    assert all(q[:, 0].max() <= 400 and q[:, 1].max() <= 200 for q in quads)


def test_a_faint_region_is_not_a_line() -> None:
    pred = np.zeros((100, 200), dtype=np.float32)
    pred[10:20, 20:120] = 0.4  # over the pixel threshold, under the box threshold
    assert ppocr.boxes_from_map(pred, width=200, height=100) == []


class Session:
    """A stand-in onnxruntime session that returns a fixed output."""

    def __init__(self, output: np.ndarray[Any, Any]) -> None:
        self.output = output
        self.inputs: list[tuple[int, ...]] = []

    def run(self, names: object, feeds: dict[str, np.ndarray[Any, Any]]) -> list[Any]:
        self.inputs.append(feeds["x"].shape)
        return [self.output]


def test_each_detected_line_is_recognised_and_read() -> None:
    chars = ["", "a", "l"]
    pred = np.zeros((1, 1, 64, 128), dtype=np.float32)
    pred[0, 0, 20:30, 10:100] = 0.9
    frames = np.zeros((1, 3, 3), dtype=np.float32)
    frames[0, 0, 1], frames[0, 1, 0], frames[0, 2, 2] = 1, 1, 1  # a, blank, l
    detector, recognizer = Session(pred), Session(frames)
    models = ppocr.Models(detector=detector, recognizer=recognizer, characters=chars, lm=None)
    page = np.full((64, 128, 3), 255, dtype=np.uint8)
    lines = models.lines(page)
    assert detector.inputs == [(1, 3, 64, 128)]
    assert len(lines) == 1
    box, probs = lines[0]
    assert box[1] < 20 and box[3] > 30  # the line's box, grown around the marked core
    assert read_line(probs, chars, LanguageScore(None), Search(width=1)) == "al"


def test_pages_are_read_in_a_child_process_that_is_replaced_after_a_while(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ppocr, "PAGES_PER_CHILD", 2)
    engine = ppocr.PpOcrEngine(tmp_path / "models", threads=3, read=ppocr_children.echo)
    images = [tmp_path / f"{n}.png" for n in range(3)]
    try:
        answers = [engine.recognize(image).split() for image in images]
    finally:
        engine.close()
    assert [a[:3] for a in answers] == [
        [str(image), str(tmp_path / "models"), "3"] for image in images
    ]
    first, second, third = (a[3] for a in answers)
    assert first == second != third


def test_a_crashed_child_is_an_ocr_error_and_the_next_page_gets_a_new_one(tmp_path: Path) -> None:
    engine = ppocr.PpOcrEngine(tmp_path, read=ppocr_children.crash)
    try:
        with pytest.raises(OcrError, match="BrokenProcessPool"):
            engine.recognize(tmp_path / "a.png")
        engine._read = ppocr_children.echo
        assert engine.recognize(tmp_path / "b.png").startswith(str(tmp_path / "b.png"))
    finally:
        engine.close()


def test_a_page_that_takes_too_long_kills_the_child(tmp_path: Path) -> None:
    engine = ppocr.PpOcrEngine(tmp_path, read=ppocr_children.hang, timeout=2)
    started = time.monotonic()
    try:
        with pytest.raises(OcrError, match="TimeoutError"):
            engine.recognize(tmp_path / "a.png")
    finally:
        engine.close()
    assert time.monotonic() - started < 30


def test_an_error_inside_the_engine_is_an_ocr_error(tmp_path: Path) -> None:
    engine = ppocr.PpOcrEngine(tmp_path, read=ppocr_children.fail)
    try:
        with pytest.raises(OcrError, match="ValueError"):
            engine.recognize(tmp_path / "a.png")
    finally:
        engine.close()


def test_the_worker_reads_with_ppocr_when_its_models_are_configured(tmp_path: Path) -> None:
    configured = page_reader(Settings(ocr_ppocr_dir=tmp_path))
    default = page_reader(Settings())
    try:
        assert isinstance(configured, TwoEngineReader)
        assert isinstance(configured.text_engine, ppocr.PpOcrEngine)
        assert isinstance(default, TwoEngineReader)
        assert isinstance(default.text_engine, TesseractEngine)
    finally:
        configured.close()
        default.close()


LINE: ppocr.Line = ((0, 0, 10, 10), np.zeros((1, 3), dtype=np.float32))


class Flaky:
    """Models whose first detection finds nothing, as three test pages once did under load."""

    def __init__(self) -> None:
        self.calls = 0

    def lines(self, page: np.ndarray[Any, Any]) -> list[ppocr.Line]:
        self.calls += 1
        return [] if self.calls == 1 else [LINE]


class Steady(Flaky):
    def lines(self, page: np.ndarray[Any, Any]) -> list[ppocr.Line]:
        self.calls += 1
        return [LINE, LINE, LINE]


def test_a_page_with_ink_and_no_line_is_read_again_and_a_blank_one_is_not() -> None:
    printed = np.full((100, 100, 3), 255, dtype=np.uint8)
    printed[40:60, 10:90] = 0
    flaky = Flaky()
    assert ppocr.detected_lines(cast(ppocr.Models, flaky), printed) == [LINE]
    assert flaky.calls == 2
    blank, flaky = np.full((100, 100, 3), 250, dtype=np.uint8), Flaky()
    assert ppocr.detected_lines(cast(ppocr.Models, flaky), blank) == []
    assert flaky.calls == 1


def test_a_page_with_lines_enough_is_read_once() -> None:
    printed = np.zeros((100, 100, 3), dtype=np.uint8)
    steady = Steady()
    assert len(ppocr.detected_lines(cast(ppocr.Models, steady), printed)) == 3
    assert steady.calls == 1


class InTurn:
    """A stand-in session that returns its outputs in turn."""

    def __init__(self, *outputs: np.ndarray[Any, Any]) -> None:
        self.outputs = list(outputs)

    def run(self, names: object, feeds: dict[str, np.ndarray[Any, Any]]) -> list[Any]:
        return [self.outputs.pop(0)]


def test_an_output_that_is_not_finite_is_run_again_and_then_an_error() -> None:
    good = np.ones((1, 2), dtype=np.float32)
    bad = np.full((1, 2), np.nan, dtype=np.float32)
    x = np.zeros((1, 3, 4, 4), dtype=np.float32)
    assert ppocr.finite_run(InTurn(bad, good), x) is good
    with pytest.raises(ppocr.NotFiniteError):
        ppocr.finite_run(InTurn(bad, bad), x)
