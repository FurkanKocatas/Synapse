"""Stand-ins for the PP-OCRv6 engine's work in its child process (tests/test_ppocr.py). They must
be module-level functions: the child is a fresh interpreter that imports them by name."""

import os
import time
from pathlib import Path

from synapse.knowledge.ppocr import NotFiniteError


def echo(image: str, directory: str, threads: int) -> str:
    return f"{image} {directory} {threads} {os.getpid()}"


def crash(image: str, directory: str, threads: int) -> str:
    os._exit(1)  # like a native crash or the kernel's out-of-memory kill


def hang(image: str, directory: str, threads: int) -> str:
    time.sleep(60)
    return ""


def fail(image: str, directory: str, threads: int) -> str:
    raise ValueError("unreadable image")


def not_finite_in_the_first_child(image: str, directory: str, threads: int) -> str:
    """Non-finite in the first child process, the page's text in any other."""
    first = Path(directory) / "first-child"
    if not first.exists():
        first.write_text(str(os.getpid()))
    if first.read_text() == str(os.getpid()):
        raise NotFiniteError("the model gave values that are not finite")
    return f"{first.read_text()} {os.getpid()}"


def never_finite(image: str, directory: str, threads: int) -> str:
    raise NotFiniteError("the model gave values that are not finite")
