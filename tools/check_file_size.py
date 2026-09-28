"""Fail when source files exceed the size limits from ADR 0015.

Limits keep modules small enough to review and prevent god files. A file that genuinely
needs to be larger must be split; there is no allowlist.

Usage: python tools/check_file_size.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (glob relative to the repository root, maximum lines)
LIMITS: list[tuple[str, int]] = [
    ("backend/src/**/*.py", 800),
    ("frontend/src/**/*.tsx", 400),
    ("frontend/src/**/*.ts", 400),
]

SKIPPED_PARTS = {"node_modules", ".venv", "dist", "paraglide"}


def main() -> int:
    violations: list[str] = []
    for pattern, limit in LIMITS:
        for path in sorted(ROOT.glob(pattern)):
            if SKIPPED_PARTS.intersection(path.parts):
                continue
            with path.open(encoding="utf-8") as handle:
                lines = sum(1 for _ in handle)
            if lines > limit:
                violations.append(f"{path.relative_to(ROOT)}: {lines} lines (limit {limit})")
    for violation in violations:
        print(violation, file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
