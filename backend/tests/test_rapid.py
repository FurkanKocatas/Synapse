"""RapidOCR's child process: what happens when it crashes, hangs or fails, without the models
(the real engine runs in the full-stack smoke test)."""

import time
from pathlib import Path

import pytest

from synapse.knowledge import rapid
from synapse.knowledge.ocr import OcrError
from tests import rapid_children


def test_pages_are_read_in_a_child_process_that_is_replaced_after_a_while(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rapid, "PAGES_PER_CHILD", 2)
    engine = rapid.RapidOcrEngine(threads=3, recognize=rapid_children.echo)
    images = [tmp_path / f"{n}.png" for n in range(3)]
    try:
        answers = [engine.recognize(image).split() for image in images]
    finally:
        engine.close()
    assert [a[:2] for a in answers] == [[str(image), "3"] for image in images]
    first, second, third = (a[2] for a in answers)
    assert first == second != third


def test_a_crashed_child_is_an_ocr_error_and_the_next_page_gets_a_new_one(
    tmp_path: Path,
) -> None:
    engine = rapid.RapidOcrEngine(recognize=rapid_children.crash)
    try:
        with pytest.raises(OcrError, match="BrokenProcessPool"):
            engine.recognize(tmp_path / "a.png")
        engine._recognize = rapid_children.echo
        assert engine.recognize(tmp_path / "b.png").startswith(str(tmp_path / "b.png"))
    finally:
        engine.close()


def test_a_page_that_takes_too_long_kills_the_child(tmp_path: Path) -> None:
    engine = rapid.RapidOcrEngine(recognize=rapid_children.hang, timeout=2)
    started = time.monotonic()
    try:
        with pytest.raises(OcrError, match="TimeoutError"):
            engine.recognize(tmp_path / "a.png")
    finally:
        engine.close()
    # The child sleeps for 60 s; closing did not wait for it.
    assert time.monotonic() - started < 30


def test_an_error_inside_the_engine_is_an_ocr_error(tmp_path: Path) -> None:
    engine = rapid.RapidOcrEngine(recognize=rapid_children.fail)
    try:
        with pytest.raises(OcrError, match="ValueError"):
            engine.recognize(tmp_path / "a.png")
    finally:
        engine.close()
