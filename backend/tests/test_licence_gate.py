"""The licence gate's reading of licence expressions (tools/check_licences.py, ADR 0016)."""

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "check_licences", Path(__file__).parents[2] / "tools" / "check_licences.py"
)
assert _spec is not None and _spec.loader is not None
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


@pytest.mark.parametrize(
    ("expression", "allowed"),
    [
        ("MIT", True),
        ("MIT License", True),
        ("Mozilla Public License 2.0 (MPL 2.0)", True),
        ("3-Clause BSD License", True),
        ("Apache-2.0 OR BSD-2-Clause", True),
        ("GPL-2.0 OR MIT", True),
        ("BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0", True),
        ("(MIT AND Zlib) OR GPL-3.0", True),
        ("Apache-2.0 WITH LLVM-exception", True),
        ("GPL-3.0", False),
        ("MIT AND GPL-3.0", False),
        ("LGPL-3.0-only", False),
        ("BSD", False),
    ],
)
def test_licence_expressions(expression: str, allowed: bool) -> None:
    assert gate.is_allowed(expression) is allowed
