import pytest

from synapse import __version__, scheduler_cli
from synapse.cli import main
from synapse.jobs.queue import Queue


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_role_is_required() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main([])
    assert exit_info.value.code == 2


def test_api_role_starts_uvicorn_with_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr("synapse.cli.uvicorn.run", lambda app, **kwargs: calls.append(kwargs))
    assert main(["api"]) == 0
    assert calls[0]["factory"] is True
    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["forwarded_allow_ips"] == "127.0.0.1"


def test_the_worker_leaves_the_maintenance_queue_to_the_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[list[Queue]] = []

    def run_worker(_settings: object, queues: list[Queue], **_options: object) -> int:
        started.append(queues)
        return 0

    monkeypatch.setattr("synapse.cli.worker_cli.main", run_worker)
    assert main(["worker"]) == 0
    assert started == [[Queue.INGEST, Queue.OCR, Queue.EMBED]]
    with pytest.raises(SystemExit):
        main(["worker", "--queue", "maintenance"])


def test_the_scheduler_role(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    started: list[object] = []

    def run_scheduler(settings: object) -> int:
        started.append(settings)
        return 0

    monkeypatch.setattr("synapse.cli.scheduler_cli.main", run_scheduler)
    assert main(["scheduler"]) == 0
    assert len(started) == 1

    def refused(_settings: object) -> int:
        raise scheduler_cli.SchedulerError("SYNAPSE_TENANT_ID is not set")

    monkeypatch.setattr("synapse.cli.scheduler_cli.main", refused)
    assert main(["scheduler"]) == 1
    assert "SYNAPSE_TENANT_ID" in capsys.readouterr().err
