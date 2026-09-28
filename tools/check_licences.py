"""Fail when a dependency has a licence that ADR 0016 does not allow.

Inputs are the JSON reports of the package managers, one per Python project:

    uv run --with pip-licenses pip-licenses --from=mixed --format=json > backend.json
    pnpm --dir frontend licenses list --json > node.json
    python tools/check_licences.py --python backend.json --python synapsectl.json --node node.json

Every exception is listed in REVIEWED with the reason; the same reasons are recorded in
docs/licences.md. Adding an exception there without a review defeats the purpose of this check.
"""

import argparse
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
    "Unlicense",
    "Zlib",
}

ALIASES = {
    "3-Clause BSD License": "BSD-3-Clause",
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
    "synapsectl": "This project's installer (proprietary).",
    "@lix-js/sdk-*": "Platform binaries of @lix-js/sdk (MIT); the binary package omits the field.",
    "caniuse-lite": "CC-BY-4.0 browser support data, used only at build time by the CSS tooling.",
    "@fontsource-variable/geist": "OFL-1.1 font, bundled with the UI (see docs/licences.md).",
    "psycopg": "LGPL-3.0, used unmodified as a separate package (see docs/licences.md).",
    "psycopg-binary": "LGPL-3.0, binary distribution of psycopg (see docs/licences.md).",
    "psycopg-pool": "LGPL-3.0, used unmodified as a separate package (see docs/licences.md).",
    "pillow": "MIT-CMU (HPND), a permissive OSI-approved licence.",
    "pypdfium2": "Apache-2.0 or BSD-3-Clause; the bundled PDFium and its libraries are permissive, "
    "FreeType needs a credit line (see docs/licences.md).",
    "antlr4-python3-runtime": "BSD-3-Clause (the ANTLR project's licence); the wheel's metadata "
    "says only BSD. Needed by omegaconf, which RapidOCR uses for its configuration.",
}


def normalise(expression: str) -> list[list[str]]:
    """Split an expression like "MIT OR (Apache-2.0 AND Zlib)" into alternatives, each a list
    of normalised identifiers that all apply."""
    cleaned = expression.strip()
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = cleaned[1:-1]
    alternatives = re.split(r"\s+OR\s+|;\s*", cleaned)
    return [
        [_identifier(part) for part in re.split(r"\s+AND\s+", option)]
        for option in alternatives
        if option.strip()
    ]


def _identifier(part: str) -> str:
    # Pip spellings can end in a bracket ("Mozilla Public License 2.0 (MPL 2.0)"), so they are
    # looked up as they are before brackets of an SPDX group are removed.
    part = part.strip()
    if part in ALIASES:
        return ALIASES[part]
    part = part.strip("() ")
    return ALIASES.get(part, part)


def is_allowed(expression: str) -> bool:
    # For "A OR B" one allowed option is enough; for "A AND B" every part must be allowed;
    # "A WITH exception" is matched as a whole.
    return any(all(i in ALLOWED for i in option) for option in normalise(expression))


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


def main(python_reports: list[Path], node_reports: list[Path]) -> int:
    packages: list[tuple[str, str]] = []
    for report in python_reports:
        packages += python_packages(json.loads(report.read_text(encoding="utf-8")))
    for report in node_reports:
        packages += node_packages(json.loads(report.read_text(encoding="utf-8")))

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
    parser = argparse.ArgumentParser(description="Check dependency licences against ADR 0016.")
    parser.add_argument(
        "--python", type=Path, action="append", default=[], help="pip-licenses JSON"
    )
    parser.add_argument("--node", type=Path, action="append", default=[], help="pnpm licenses JSON")
    arguments = parser.parse_args()
    if not (arguments.python or arguments.node):
        parser.error("give at least one report")
    sys.exit(main(arguments.python, arguments.node))
