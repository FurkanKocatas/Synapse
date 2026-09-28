import json
import logging

import pytest
import structlog

from synapse.kernel.config import Settings
from synapse.kernel.logging import configure_logging


def test_json_lines_carry_bound_context(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(log_format="json"))
    structlog.contextvars.bind_contextvars(request_id="r-1")
    try:
        structlog.get_logger("test").info("something.happened", count=3)
    finally:
        structlog.contextvars.clear_contextvars()

    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["event"] == "something.happened"
    assert line["request_id"] == "r-1"
    assert line["count"] == 3
    assert line["level"] == "info"


def test_standard_library_logs_are_rendered_as_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(log_format="json"))
    logging.getLogger("uvicorn.error").warning("from uvicorn")

    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["event"] == "from uvicorn"
    assert line["logger"] == "uvicorn.error"
