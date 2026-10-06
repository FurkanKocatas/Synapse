# Backups and restores: design and operation

Status: implemented, 2026-10-06. Decision record: [ADR 0021](../adr/0021-backups.md). Code: [synapsectl/backup.py](../../synapsectl/src/synapsectl/backup.py), the containers in [render.py](../../synapsectl/src/synapsectl/render.py) (`backup_services`).

## Setting up

```toml
[backup]
repository = "/mnt/backup/synapse"   # a mounted NAS share or disk; not under staging_dir
# staging_dir = "/var/lib/synapse/backup"
# time = "02:30"
# keep_daily = 7
# keep_weekly = 4
# keep_monthly = 6
```

```bash
sudo synapsectl backup init     # creates the secret backup_password, renders the backup
                                # containers, sets up the repository encrypted with that password
sudo synapsectl apply           # installs the timers
sudo synapsectl backup          # the first backup, now
```

Keep a copy of `/etc/synapse/secrets/backup_password` away from the machine (a password manager, a sealed envelope): without it no backup can be restored, and with it anyone holding the repository can read it.

## Commands

| Command | What it does |
|---|---|
| `synapsectl backup init` | Creates the backup password if it is missing, renders the files again with the backup containers, and sets up the repository unless it exists |
| `synapsectl backup` | Dumps the database, writes the manifest, copies the dump, the configuration and the uploaded files into a snapshot, then forgets and prunes what the retention no longer keeps |
| `synapsectl backup list` | This installation's snapshots |
| `synapsectl backup verify [--snapshot ID]` | Restores the dump into the scratch database `synapse_drill`, compares every table's rows with the manifest, checks that the live audit log still holds the backup's last audit event with the same hash ([audit.md](audit.md)), drops it, and has restic read 5% of the data back |
| `synapsectl restore [--snapshot ID] [--replace] [--yes]` | Replaces the database and the uploaded files with a snapshot's; asks for the installation's slug unless `--yes` |
| `synapsectl restore --configuration-from REPO --password-file F` | On a new machine: writes `synapse.toml` and the secrets from the latest snapshot; never overwrites |

`latest` is always this installation's latest snapshot (`--host synapse-<instance id>`), so several installations can share one repository.

## A snapshot

| Path in the snapshot | Contents |
|---|---|
| `/backup/data/synapse.dump` | `pg_dump --format=custom` of the database `synapse` |
| `/backup/data/manifest.json` | When, the instance and tenant IDs, the image version, the schema revision, every table's rows and the dump's size and SHA-256 |
| `/backup/data/config/` | `synapse.toml` and the secrets, with their modes and owners |
| `/data/blobs/` | The uploaded files (the `blobs` volume) |

The rows are counted in the dump itself (`pg_restore --data-only`, the rows between each table's `COPY` line and its end marker), so they describe the same moment as the data even while users keep working. Model files are not backed up: they come with the release.

## What a restore checks

1. The snapshot is this installation's (the instance ID) and was taken with the same image version; otherwise it stops and says what to do (restore the configuration first, or set the version, restore, then upgrade).
2. The restored dump's SHA-256 is the manifest's.
3. Secrets that differ from the backup's are reported; this machine's are kept.
4. The services are stopped and the database started; a database holding a tenant is replaced only with `--replace`.
5. Bootstrap recreates the roles (a dump holds no roles), the database is dropped and recreated from the dump with its grants, and every table's rows must equal the manifest's.
6. The uploaded files are emptied and restored from the same snapshot, with their owners.

`synapsectl apply` then starts the services; the migrations find the schema at the backup's revision.

## On a new machine

```bash
sudo synapsectl restore --configuration-from /mnt/backup/synapse --password-file ./backup_password
sudo synapsectl models fetch    # or the offline bundle's files
sudo synapsectl render
sudo synapsectl restore --yes
sudo synapsectl apply
```

The hostname comes back with `synapse.toml`, so registered passkeys keep working once the name points to the new machine.

## Schedule and status

`apply` writes `synapse-backup.service` and `.timer` (every night at `time`) and `synapse-backup-verify.service` and `.timer` (on the first day of January, April, July and October, three hours later) into `/etc/systemd/system` and enables the timers; `Persistent=true` runs a missed one at the next boot. Without root or systemd it prints the two commands to schedule instead.

Each run records its outcome in `staging_dir/status.json`: the latest backup and verification, and separately the last good one of each. `doctor` reads it and warns (never fails) when:

- `[backup] repository` is not set: no backups are taken;
- the directory holds no repository: the disk or share is not mounted, or `backup init` was not run;
- no backup has succeeded yet, or the last one failed (with the failure's first line);
- the last good backup is more than 2 days old.

## Tests

- [tests/test_backup.py](../../synapsectl/tests/test_backup.py): every step's exact command against a scripted Docker, the order of a restore, refusals (another installation, another image version, a damaged dump, rows that differ, a database holding data), the scratch database dropped after a failed verification, the configuration restored on a new machine, the schedule, doctor's warnings and the rendered containers.
- `tools/stack_smoke.sh --with-backup`, in CI on every push: the full stack is backed up and verified with this code ([tools/smoke_backup.py](../../tools/smoke_backup.py)), removed with its volumes and restored; the documents are listed again, their files download byte for byte, their pages are in the database, the audit chain verifies, and a new upload is stored and parsed.
