"""Fail when a dependency has a licence that ADR 0016 does not allow.

Inputs are the JSON reports of the two package managers:

    uv run --with pip-licenses pip-licenses --from=mixed --format=json > python-licences.json
    pnpm --dir frontend licenses list --json > node-licences.json
    python tools/check_licences.py python-licences.json node-licences.json

Every exception is listed in REVIEWED with the reason; the same reasons are recorded in
docs/licences.md. Adding an exception there without a review defeats the purpose of this check.
"""

import json
import re
import sys
from pathlib import Path

# SPDX identifiers allowed without review (ADR 0016), plus the spellings pip metadata uses.
ALLOWED = {
    "0BSD",
    "Apache-2.0",
    "Apache-2.0 WITH LLVM-exception",
    "BlueOak-1.0.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "CC0-1.0",
    "ISC",
    "MIT",
    "MIT-0",
    "MPL-2.0",
    "PostgreSQL",
    "PSF-2.0",
    "Python-2.0",
    "Unicode-3.0",
    "Zlib",
}

ALIASES = {
    "Apache Software License": "Apache-2.0",
    "BSD License": "BSD-3-Clause",
    "ISC License (ISCL)": "ISC",
    "MIT License": "MIT",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "Python Software Foundation License": "PSF-2.0",
}

# Package name (or prefix ending in "*") -> reason. Keep in sync with docs/licences.md.
REVIEWED = {
    "synapse": "This project itself (proprietary).",
    "@lix-js/sdk-*": "Platform binaries of @lix-js/sdk (MIT); the binary package omits the field.",
    "caniuse-lite": "CC-BY-4.0 browser support data, used only at build time by the CSS tooling.",
    "psycopg": "LGPL-3.0, used unmodified as a separate package (see docs/licences.md).",
    "psycopg-binary": "LGPL-3.0, binary distribution of psycopg (see docs/licences.md).",
    "psycopg-pool": "LGPL-3.0, used unmodified as a separate package (see docs/licences.md).",
}


def normalise(expression: str) -> list[str]:
    """Split an expression like "MIT OR Apache-2.0" into normalised identifiers."""
    cleaned = expression.strip()
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = cleaned[1:-1]
    parts = re.split(r"\s+OR\s+|;\s*", cleaned)
    return [ALIASES.get(part.strip(), part.strip()) for part in parts if part.strip()]


def is_allowed(expression: str) -> bool:
    # For "A OR B" one allowed option is enough; "A WITH exception" is matched as a whole.
    return any(identifier in ALLOWED for identifier in normalise(expression))


def is_reviewed(name: str) -> bool:
    for pattern in REVIEWED:
        if pattern.endswith("*") and name.startswith(pattern[:-1]):
            return True
        if name == pattern:
            return True
    return False


def python_packages(report: list[dict[str, str]]) -> list[tuple[str, str]]:
    return [(entry["Name"], entry["License"]) for entry in report]


def node_packages(report: dict[str, list[dict[str, object]]]) -> list[tuple[str, str]]:
    return [
        (str(entry["name"]), licence) for licence, entries in report.items() for entry in entries
    ]


def main(python_report: Path, node_report: Path) -> int:
    packages = python_packages(json.loads(python_report.read_text(encoding="utf-8")))
    packages += node_packages(json.loads(node_report.read_text(encoding="utf-8")))

    rejected = [
        f"{name}: {licence}"
        for name, licence in sorted(set(packages))
        if not is_allowed(licence) and not is_reviewed(name)
    ]
    for line in rejected:
        print(f"licence not allowed: {line}", file=sys.stderr)
    print(f"licences: {len(packages)} packages checked, {len(rejected)} rejected")
    return 1 if rejected else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:  # noqa: PLR2004  (two report paths)
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
