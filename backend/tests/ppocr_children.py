"""Stand-ins for the PP-OCRv6 engine's work in its child process (tests/test_ppocr.py). They must
be module-level functions: the child is a fresh interpreter that imports them by name."""

import os
import time


def echo(image: str, directory: str, threads: int) -> str:
    return f"{image} {directory} {threads} {os.getpid()}"


def crash(image: str, directory: str, threads: int) -> str:
    os._exit(1)  # like a native crash or the kernel's out-of-memory kill


def hang(image: str, directory: str, threads: int) -> str:
    time.sleep(60)
    return ""


def fail(image: str, directory: str, threads: int) -> str:
    raise ValueError("unreadable image")
