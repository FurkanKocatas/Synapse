from pathlib import Path

import pytest

from synapse.kernel.secrets import SecretError, read_secret


def test_trailing_newline_is_removed(tmp_path: Path) -> None:
    path = tmp_path / "secret"
    path.write_text("s3cret\n", encoding="utf-8")
    assert read_secret(path) == "s3cret"


def test_missing_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(SecretError, match="not found"):
        read_secret(tmp_path / "absent")


def test_empty_file_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "secret"
    path.write_text("\n", encoding="utf-8")
    with pytest.raises(SecretError, match="empty"):
        read_secret(path)
