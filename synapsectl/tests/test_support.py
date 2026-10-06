"""The support bundle: what it holds, and what the redaction removes from real log lines."""

import subprocess
import tarfile
from collections.abc import Sequence
from pathlib import Path

import pytest

from synapsectl import cli, doctor, support
from synapsectl.config import SynapseConfig, save

SUPERUSER = "Vq3nX8pL0aZr7Ty2Kc5mWd9Hs4Jb6Ne1"
CADDY = (
    '{"level":"info","logger":"http.log.access.log0","msg":"handled request","request":'
    '{"remote_ip":"172.29.0.1","client_ip":"10.20.30.40","method":"POST",'
    '"uri":"/api/collections/7c1e/documents?filename=Karar%202026-35.pdf&kind=pdf",'
    '"headers":{"X-Synapse-Csrf":["e36a69e185dedbbb04c3d604883707f0"],"Cookie":["REDACTED"],'
    '"Authorization":["Bearer abc.def"]}}}'
)


def redactor() -> support.Redactor:
    secrets = {
        "postgres_superuser": SUPERUSER,
        "admin_conninfo": f"postgresql://postgres:{SUPERUSER}@db:5432/postgres",
        "short": "abc",
    }
    return support.Redactor(secrets, ["172.29.0.0/24"])


def test_secrets_and_credentials_are_removed() -> None:
    redact = redactor()
    text = redact(
        f"connect postgresql://postgres:{SUPERUSER}@db:5432/postgres\n"
        f"password={SUPERUSER}\n"
        "DSN https://user:hunter22@mirror.example/simple abc\n"
    )
    assert SUPERUSER not in text
    assert "hunter22" not in text
    assert "[secret admin_conninfo]" in text  # the longer secret, replaced whole
    assert "password=[secret postgres_superuser]" in text
    assert "https://user:[secret]@mirror.example" in text
    assert text.endswith("abc\n")  # too short to be told from ordinary text


def test_a_web_front_request_keeps_its_shape_without_personal_data() -> None:
    redact = redactor()
    text = redact(CADDY)
    assert "10.20.30.40" not in text
    assert '"remote_ip":"172.29.0.1"' in text  # the stack's own network stays
    assert "Karar" not in text
    assert "?filename=[removed]&kind=[removed]" in text
    assert "e36a69e1" not in text
    assert '"X-Synapse-Csrf":["[removed]"]' in text
    assert "Bearer" not in text
    # the same address gets the same pseudonym within a bundle, another bundle another one
    assert redact(CADDY) == text
    assert redactor()(CADDY) != text


@pytest.mark.parametrize(
    ("line", "removed"),
    [
        ("identity.login.failed for jane.doe@example.org", "jane.doe@example.org"),
        (
            "DETAIL:  Key (tenant_id, email)=(7c1e, ali@demo.local) already exists.",
            "7c1e, ali",
        ),
        ("client 2001:db8:85a3::8a2e:370:7334 closed", "2001:db8:85a3::8a2e:370:7334"),
        ("from 192.168.1.23:51234", "192.168.1.23"),
    ],
)
def test_personal_data_in_log_lines_is_removed(line: str, removed: str) -> None:
    assert removed not in redactor()(line)


@pytest.mark.parametrize(
    "line",
    [
        "117.17.970.718 I slot      release: id  0 | task 1493",
        '"timestamp": "2026-10-06T06:58:23.617013Z"',
        "pgvector 0.8.6, PostgreSQL 18.6, pypdfium2 5.1.0",
        "listening on 127.0.0.1:8080 and [::1]:8080",
    ],
)
def test_times_versions_and_loopback_addresses_stay(line: str) -> None:
    assert redactor()(line) == line


class Stack:
    """The installation's Docker: two services, logs that hold what must not leave."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(
        self, args: Sequence[str], *, interactive: bool = False
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        out = ""
        if "ps" in args:
            out = '{"Service":"api","State":"running"}\n{"Service":"worker","State":"exited"}\n'
        elif "logs" in args:
            out = f"{args[-1]} started by admin@demo.local with {SUPERUSER}\n"
        elif list(args[:2]) == ["docker", "version"]:
            out = "Server: Docker Engine 28.1\n"
        return subprocess.CompletedProcess(list(args), 0, out, "")


def test_the_bundle_holds_the_state_and_no_secret(config: SynapseConfig, tmp_path: Path) -> None:
    config.paths.secrets_dir.mkdir(parents=True)
    (config.paths.secrets_dir / "postgres_superuser").write_text(SUPERUSER + "\n")
    config_file = tmp_path / "synapse.toml"
    save(config, config_file)
    stack = Stack()
    asked: list[bool] = []

    def checks(_config: SynapseConfig, *, stack_running: bool) -> list[doctor.Check]:
        asked.append(stack_running)
        return [doctor.Check("docker", doctor.Status.OK, "Docker 28.1")]

    output = tmp_path / "out" / "bundle.tar.gz"
    support.write_bundle(config, config_file, output, run=stack, echo=lambda _: None, checks=checks)

    assert output.stat().st_mode & 0o777 == 0o600
    contents = {}
    with tarfile.open(output) as tar:
        for member in tar.getmembers():
            handle = tar.extractfile(member)
            assert handle is not None
            contents[member.name.removeprefix("bundle/")] = handle.read().decode()
    assert {"README.txt", "versions.txt", "synapse.toml", "secrets.txt", "doctor.txt"} <= set(
        contents
    )
    assert {"logs/api.log", "logs/worker.log", "services.json", "disk.txt"} <= set(contents)
    everything = "".join(contents.values())
    assert SUPERUSER not in everything
    assert "admin@demo.local" not in everything
    assert "api started by [email] with [secret postgres_superuser]" in contents["logs/api.log"]
    assert "postgres_superuser: mode" in contents["secrets.txt"]
    assert "OK    docker: Docker 28.1" in contents["doctor.txt"]
    assert asked == [True]  # a service is running, so its ports are expected in use
    assert ["--tail", str(support.LOG_LINES), "worker"] == stack.calls[-1][-3:]


def test_a_secret_that_cannot_be_read_stops_the_bundle(
    monkeypatch: pytest.MonkeyPatch, config: SynapseConfig, tmp_path: Path
) -> None:
    config.paths.secrets_dir.mkdir(parents=True)
    (config.paths.secrets_dir / "csrf_key").write_text("x" * 32)
    config_file = tmp_path / "synapse.toml"
    save(config, config_file)

    def unreadable(_path: Path) -> str:
        raise PermissionError("denied")

    monkeypatch.setattr(support, "read_secret", unreadable)
    output = tmp_path / "bundle.tar.gz"
    with pytest.raises(support.SupportError, match="csrf_key"):
        support.write_bundle(config, config_file, output, run=Stack(), echo=lambda _: None)
    assert not output.exists()


def test_the_support_bundle_command(
    monkeypatch: pytest.MonkeyPatch,
    config: SynapseConfig,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_file = tmp_path / "synapse.toml"
    save(config, config_file)
    written: list[Path] = []

    def write_bundle(_config: SynapseConfig, _path: Path, output: Path) -> Path:
        written.append(output)
        return output

    monkeypatch.setattr(support, "write_bundle", write_bundle)
    command = ["--config", str(config_file), "support-bundle"]
    assert cli.main([*command, "--output", str(tmp_path / "b.tar.gz")]) == 0
    assert cli.main(command) == 0
    assert written[0] == tmp_path / "b.tar.gz"
    assert written[1].name.startswith("synapse-support-demo-")

    def refused(*_args: object) -> Path:
        raise support.SupportError("cannot read the secret csrf_key (run as root)")

    monkeypatch.setattr(support, "write_bundle", refused)
    assert cli.main(command) == 1
    assert "run as root" in capsys.readouterr().err
