# Operations: what the operations page shows

Status: the data, 2026-10-06; the page itself waits for its design. Decision record: [ADR 0014](../adr/0014-observability.md). Code: [backend/src/synapse/operations/](../../backend/src/synapse/operations/), the route in [operations_routes.py](../../backend/src/synapse/api/operations_routes.py).

`GET /api/admin/operations` (permission `operations.view`, administrators) answers in one tenant transaction, from the database, the blob volume the API mounts and the model servers' `/health`, so it works without any observability stack.

| Part | What it is | From |
|---|---|---|
| `services` | The database; the worker and the scheduler, running when they hold a connection (each process names its connections, and another role's session shows its name though not its queries); each model server the API calls, healthy once its model is loaded (3 seconds at most) | `pg_stat_activity`, `/health` |
| `queues` | Per queue: jobs waiting, running and failed, this installation's only | `procrastinate_jobs` |
| `documents`, `deleted_waiting` | Live documents by the status of their latest version; deleted ones not purged yet | `documents`, `document_versions` |
| `pages` | Pages of those versions: all, read by OCR, needing OCR but not read, with identifiers OCR was unsure of | `document_pages` |
| `storage` | Bytes of uploaded files and of the database; free and total space where the files are | `blobs`, `pg_database_size`, the volume |
| `runs` | The latest run of each kind, and the latest that succeeded: `backup`, `backup_verify`, `files_sweep`, `audit_verify` | `operation_runs` |
| `problems` | The consistency checks of ADR 0003 that are not zero: ready versions without chunks, chunks of ready versions without vectors, documents deleted more than a day ago and not purged, blob rows no version names | live queries |

## Runs

`operation_runs` (migration 0022) keeps one row per run: kind, success, start, end and details (counts, or the first line of an error).

- **Backups and their verifications** run on the host ([backup.md](backup.md)); after each, synapsectl runs `synapse operations record` in a one-off API container. A run that cannot be recorded (the database is down) still counts: `status.json` on the host has it, and `doctor` reads that.
- **The nightly file sweep** (00:40 UTC) records what it removed and whether any blob row has lost its file ([knowledge-base.md](knowledge-base.md#deleting)).
- **The nightly audit verification** (01:20 UTC) recomputes the chain and compares the checkpoints with it, as `synapse audit verify` does ([audit.md](audit.md)), and logs an error when either is broken.

A restored database holds the runs up to its dump, not the backup that restored it.

## Tests

[tests/db/test_operations.py](../../backend/tests/db/test_operations.py) against the real database, queue and roles: the counts after uploads, processing and a delete; a process seen by its connections under another role; a broken invariant reported; backups recorded through the command line, the latest and the latest good one; members refused. The scheduler's records in [tests/db/test_maintenance.py](../../backend/tests/db/test_maintenance.py); synapsectl's in [synapsectl/tests/test_backup.py](../../synapsectl/tests/test_backup.py), where a run that cannot be recorded does not fail.

## Not done yet

- The page itself, after its design is approved: health, queues with a way to retry failed jobs, ingestion progress, pages read by OCR, disk, the last backup and its verification, and, with modules, the licence.
- Sending alerts (email) when a check fails or a backup is late.
