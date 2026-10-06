# 0021. Backups are taken from the host, into a restic repository

- Status: accepted
- Date: 2026-10-06

## Context

[ADR 0012](0012-installer-modules-licensing.md) decided what a backup holds (`pg_dump -Fc`, the uploaded files, `synapse.toml` and the secrets), that restic encrypts it, the retention (7 daily, 4 weekly, 6 monthly) and a quarterly restore drill. Three details of the earlier records do not fit how the product is now built:

- [ADR 0002](0002-process-topology.md) gives backups to the scheduler role. The scheduler runs in a read-only container on the application network with only its own database role ([ADR 0013](0013-secrets-and-network-security.md)). To back up it would need the repository's directory, every uploaded file and credentials that read every table: one long-running process holding all of the installation's data. A restore cannot run there at all, since it replaces the database the scheduler runs on.
- [ADR 0013](0013-secrets-and-network-security.md) lists a `synapse_backup` role. A restore needs the superuser in any case (it drops and creates the database), and a read-only role would need its grants kept up to date by every migration.
- ADR 0012 names S3-compatible targets. A restic container without a network can only reach a directory.

## Decision

1. `synapsectl` takes the backups on the host, as root: `synapsectl backup` every night at `[backup] time` (default 02:30) and `synapsectl backup verify` on the first day of each quarter, three hours later. `apply` installs the two systemd timers.
2. The work is done by three containers in the rendered compose file, in the `backup` profile so that `up` never starts them, each run for one step and removed: `pgtools` (the database image's client tools as the superuser, on the internal network), `restic` (restic 0.19.1, pinned by digest, without a network, the uploaded files read-only) and `restic-restore` (the same, the uploaded files writable). No running service gets another role, password or volume.
3. The repository is a directory, `[backup] repository`: a mounted NAS share or a disk. restic encrypts it with the secret `backup_password`, which `init` creates; a copy of it is kept away from the machine.
4. A snapshot holds the dump, its manifest (installation, tenant, image version, schema revision, every table's rows counted in the dump itself, the dump's SHA-256), `synapse.toml` with the secrets, and the uploaded files. The dump is taken first: an uploaded file is never changed, so one uploaded in between is extra, never missing.
5. A restore needs the image version that took the backup. It checks the dump's SHA-256, drops the database and recreates it from the dump, compares every table's rows with the manifest, then empties the uploaded files and restores them from the same snapshot. It refuses to replace a database that holds a tenant unless told to (`--replace`). On a new machine, `restore --configuration-from` first brings back `synapse.toml` and the secrets.
6. A verification restores the latest dump into a scratch database, compares every table's rows with the manifest and drops it; then restic reads 5% of the repository's data back.
7. Each backup's and verification's outcome is kept in `status.json` in the staging directory. `doctor` warns when backups are not set up, the repository is missing, the last backup failed or the last good one is more than two days old; it never fails on them, so a missing backup cannot stop `apply` from repairing an installation.

## Consequences

- Backups and restores need nothing from the application's services: they work when the API is down, which is when a restore is needed.
- The running services keep the privileges they had; the superuser's password is used only by the short-lived `pgtools` container.
- The `synapse_backup` role of ADR 0013 is not created, and the scheduler role of ADR 0002 does not take backups.
- The Operations page cannot read the host's `status.json`. When it is built, the backup writes its outcome where the API reads it (a row in the database, written through the API's command line).
- S3-compatible targets come later, as a restic container allowed to reach that one host; until then, a NAS share mounted on the host.
- A backup taken with one image version is restored with that version, then upgraded; restoring across versions is refused.
- Tested by [tests/test_backup.py](../../synapsectl/tests/test_backup.py) with a scripted Docker, and in CI by the full-stack smoke test: it backs the stack up, removes it with its volumes, restores it, and checks the documents, their files and the audit chain came back and that a new upload is stored.

## Alternatives considered

- **Backups in the scheduler role**: see the context; it would concentrate every credential and file in one long-running container and could not restore.
- **Continuous WAL archiving for point-in-time recovery**: a second archive target that must never fall behind, and a restore that replays it. A nightly dump loses at most a day, which ADR 0012 accepted.
- **Counting rows in the live database after the dump**: rows written in between would make the counts disagree with the dump. They are counted in the dump's own data instead.
- **Borg**: its repositories are reached through borg itself on the far side or over SSH; restic writes to a plain directory now and to S3-compatible storage later, as one static binary under BSD-2-Clause.
