"""Backup and restore of the full-stack smoke test's installation (tools/stack_smoke.sh
--with-backup), with synapsectl's own code and backup containers (render.backup_services) added
to the running compose project. Runs as root, as synapsectl does on a customer's machine: the
containers write files owned by root and restore the uploaded files to their owner.

    python tools/smoke_backup.py WORKDIR PROJECT TENANT_ID backup   (init, back up, verify)
    python tools/smoke_backup.py WORKDIR PROJECT TENANT_ID restore  (after the volumes are gone)
"""

import sys
import uuid
from pathlib import Path

import yaml
from synapsectl import backup, render
from synapsectl.config import Backup, Instance, Paths, SynapseConfig, save

ROOT = Path(__file__).resolve().parents[1]
INSTANCE = uuid.UUID("00000000-0000-4000-8000-00000000b4c4")


def installation(work: Path, project: str, tenant: str) -> tuple[SynapseConfig, Path]:
    """The smoke test's stack as synapsectl sees it, with backups into WORKDIR."""
    config = SynapseConfig(
        instance=Instance(
            id=INSTANCE,
            tenant_id=uuid.UUID(tenant),
            organization="Smoke",
            slug="smoke",
            hostname="localhost",
        ),
        paths=Paths(secrets_dir=ROOT / ".dev" / "secrets", render_dir=work / "rendered"),
        backup=Backup(repository=work / "repository", staging_dir=work / "staging"),
    )
    config_file = work / "synapse.toml"
    if not config_file.exists():
        save(config, config_file)
        password = work / "backup_password"
        password.write_text(uuid.uuid4().hex + "\n", encoding="utf-8")
        password.chmod(0o400)
        compose = {
            "name": project,
            "include": [str(ROOT / "deploy" / "compose.stack.yml")],
            "services": render.backup_services(config),
            "secrets": {"backup_password": {"file": str(password)}},
        }
        config.paths.render_dir.mkdir(parents=True)
        (config.paths.render_dir / "compose.yml").write_text(
            yaml.safe_dump(compose, sort_keys=False), encoding="utf-8"
        )
    return config, config_file


def main() -> int:
    work, project, tenant, action = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
    config, config_file = installation(work, project, tenant)
    if action == "backup":
        backup.init_repository(config)
        backup.backup(config, config_file)
        backup.verify(config)
        return 0
    manifest = backup.restore(config)
    print(f"restored {sum(manifest.rows.values())} rows of {len(manifest.rows)} tables")
    return 0


if __name__ == "__main__":
    sys.exit(main())
