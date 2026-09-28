"""Generating the installation's secrets (ADR 0013).

Every secret is random, generated on the customer's machine, and never typed or copied between
installations. Existing files are kept, so re-running is harmless; rotating a secret means
deleting its file and running ``synapsectl init`` again (and restarting what uses it).

Compose mounts secret files as they are on the host, so each file is owned by the container
user that reads it and readable by that user only.
"""

import os
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path

from synapsectl.config import SynapseConfig, TlsMode

APP_UID = 10001  # the application and web containers
POSTGRES_UID = 999  # the database container


@dataclass(frozen=True)
class SecretFile:
    name: str
    owner_uid: int


DATABASE_ROLES = ("synapse_migrator", "synapse_api", "synapse_worker", "synapse_scheduler")

REQUIRED = (
    SecretFile("postgres_superuser", POSTGRES_UID),
    SecretFile("admin_conninfo", APP_UID),
    *(SecretFile(f"db_{role}", APP_UID) for role in DATABASE_ROLES),
    SecretFile("csrf_key", APP_UID),
    SecretFile("totp_key", APP_UID),
    SecretFile("audit_signing_key", APP_UID),
)
TLS_FILES = (SecretFile("tls_certificate", APP_UID), SecretFile("tls_private_key", APP_UID))


def required_files(config: SynapseConfig) -> tuple[SecretFile, ...]:
    return REQUIRED + (TLS_FILES if config.tls.mode is TlsMode.PROVIDED else ())


def _random_text() -> str:
    # 32 random bytes as unpadded base64url: usable both as a password and as a binary key.
    return secrets.token_urlsafe(32)


def _write_once(path: Path, value: str) -> bool:
    if path.exists():
        return False
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(value + "\n")
    return True


def generate(config: SynapseConfig) -> list[str]:
    """Create missing secrets; returns the names that were created."""
    directory = config.paths.secrets_dir
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    created = []
    for name in ("postgres_superuser", *(f"db_{role}" for role in DATABASE_ROLES)):
        if _write_once(directory / name, _random_text()):
            created.append(name)
    for name in ("csrf_key", "totp_key", "audit_signing_key"):
        if _write_once(directory / name, _random_text()):
            created.append(name)
    superuser = (directory / "postgres_superuser").read_text(encoding="utf-8").strip()
    if _write_once(
        directory / "admin_conninfo", f"postgresql://postgres:{superuser}@db:5432/postgres"
    ):
        created.append("admin_conninfo")
    if config.tls.mode is TlsMode.PROVIDED:
        created += _copy_certificate(config, directory)
    _set_owners(config, directory)
    return created


def _copy_certificate(config: SynapseConfig, directory: Path) -> list[str]:
    assert config.tls.certificate and config.tls.private_key  # noqa: S101  (validated by the model)
    copied = []
    for source, name in (
        (config.tls.certificate, "tls_certificate"),
        (config.tls.private_key, "tls_private_key"),
    ):
        target = directory / name
        target.unlink(missing_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o400)
        copied.append(name)
    return copied


def _set_owners(config: SynapseConfig, directory: Path) -> None:
    # Only root can hand files to other users. Development runs as a normal user, where Docker
    # Desktop does not enforce host ownership anyway; doctor reports it on real hosts.
    if os.geteuid() != 0:
        return
    for secret in required_files(config):
        os.chown(directory / secret.name, secret.owner_uid, secret.owner_uid)
