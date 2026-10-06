"""The auditor's routes, without a database."""

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import Request

from synapse.api.audit_routes import _signing_key
from synapse.kernel.config import Settings
from synapse.kernel.logging import configure_logging


class Events(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        if isinstance(record.msg, dict):
            self.events.append(record.msg)


def test_an_unreadable_signing_key_is_logged(tmp_path: Path) -> None:
    configure_logging(Settings(log_format="json"))
    state = SimpleNamespace(audit_signing_key_file=tmp_path / "missing")
    request = cast("Request", SimpleNamespace(app=SimpleNamespace(state=state)))
    handler = Events()
    logger = logging.getLogger("synapse.api.audit_routes")
    logger.addHandler(handler)
    try:
        assert _signing_key(request) is None
    finally:
        logger.removeHandler(handler)
    [event] = handler.events
    assert event["event"] == "audit.signing_key_unreadable"
    assert event["level"] == "error"


def test_a_readable_signing_key_is_returned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = object()
    monkeypatch.setattr("synapse.api.audit_routes.audit.load_signing_key", lambda _path: key)
    state = SimpleNamespace(audit_signing_key_file=tmp_path / "key")
    request = cast("Request", SimpleNamespace(app=SimpleNamespace(state=state)))
    assert _signing_key(request) is key
