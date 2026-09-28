"""Stand-ins for RapidOCR's work in its child process (tests/test_rapid.py). They must be
module-level functions: the child is a fresh interpreter that imports them by name."""

import os
import time


def echo(image: str, threads: int) -> str:
    return f"{image} {threads} {os.getpid()}"


def crash(image: str, threads: int) -> str:
    os._exit(1)  # like a native crash or the kernel's out-of-memory kill


def hang(image: str, threads: int) -> str:
    time.sleep(60)
    return ""


def fail(image: str, threads: int) -> str:
    raise ValueError("unreadable image")
