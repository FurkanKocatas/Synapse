"""RapidOCR, the second reading of a page's identifiers (docs/benchmarks/ocr.md), in a child
process.

Its onnxruntime sessions keep memory for every input shape they have seen: one process reading
40 to 60 pages of different sizes peaked at 1.7 to 2.0 GB and did not give it back. A crash in
native code would also take the whole worker with it. So RapidOCR runs in one child process,
replaced after ``PAGES_PER_CHILD`` pages, and a page that takes too long kills the child
instead of hanging the job. Pages go to the child one at a time.

The models are fetched when the image is built (``fetch_models``), so reading needs no network.
"""

import multiprocessing
import threading
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any

from synapse.knowledge.ocr import OCR_TIMEOUT_SECONDS, OcrError

PAGES_PER_CHILD = 25


# rapidocr is imported where it is used: it loads onnxruntime and OpenCV, which the API process
# (it imports this package too) and the worker process (only its child reads) do not need.


def _params(threads: int) -> dict[str, Any]:
    from rapidocr import LangRec, ModelType, OCRVersion  # noqa: PLC0415  (see above)

    return {
        # The Latin recogniser exists for PP-OCRv5, in the mobile size only.
        "Rec.lang_type": LangRec.LATIN,
        "Rec.ocr_version": OCRVersion.PPOCRV5,
        "Rec.model_type": ModelType.MOBILE,
        # One line at a time instead of six padded to the widest: 41% faster, and identifiers
        # as good or better on every condition of the benchmark.
        "Rec.rec_batch_num": 1,
        "Global.log_level": "error",
        # onnxruntime otherwise uses every core; the worker decides how much runs at once.
        "EngineConfig.onnxruntime.intra_op_num_threads": threads,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
    }


def fetch_models() -> None:
    """Download the models (checked against RapidOCR's own SHA-256); run at image build time."""
    from rapidocr import RapidOCR  # noqa: PLC0415  (see above)

    RapidOCR(params=_params(1))


# The child's engine, created by its first page and kept for the pages after it.
_engines: dict[int, Any] = {}


def _recognize(image: str, threads: int) -> str:  # runs in the child process
    if threads not in _engines:
        from rapidocr import RapidOCR  # noqa: PLC0415  (see above)

        _engines[threads] = RapidOCR(params=_params(threads))
    # RapidOCR remembers these switches from the previous call, so they are always passed.
    output = _engines[threads](image, use_det=True, use_cls=True, use_rec=True)
    return "\n".join(output.txts or ())


class RapidOcrEngine:
    name = "rapidocr-latin"

    def __init__(
        self,
        threads: int = 1,
        *,
        recognize: Callable[[str, int], str] = _recognize,
        timeout: float = OCR_TIMEOUT_SECONDS,
    ) -> None:
        """``recognize`` runs in the child; it must be a module-level function (tests replace
        it to exercise crashes and timeouts without the models)."""
        self._threads = threads
        self._recognize = recognize
        self._timeout = timeout
        self._lock = threading.Lock()
        self._pool: ProcessPoolExecutor | None = None

    def recognize(self, image: Path) -> str:
        with self._lock:
            if self._pool is None:
                self._pool = ProcessPoolExecutor(
                    max_workers=1,
                    # A fresh interpreter: forking a threaded worker is unsafe.
                    mp_context=multiprocessing.get_context("spawn"),
                    max_tasks_per_child=PAGES_PER_CHILD,
                )
            future = self._pool.submit(self._recognize, str(image), self._threads)
            try:
                return future.result(timeout=self._timeout)
            except (BrokenProcessPool, TimeoutError) as error:
                self._discard()
                raise OcrError(f"rapidocr failed: {type(error).__name__}") from error
            except Exception as error:
                # Raised inside RapidOCR, for example by an image it cannot handle; the child
                # is still fine.
                raise OcrError(f"rapidocr failed: {type(error).__name__}") from error

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
