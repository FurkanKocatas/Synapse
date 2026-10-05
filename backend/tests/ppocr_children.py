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


def two(image: str, directory: str, threads: int) -> tuple[str, str]:
    # the second reading has a different decision number and the same date
    return "Karar 2026/35 ile 15.03.2025 tarihli", "Karar 2026/36 ile 15.03.2025 tarihli"
