# Operations: what the operations page shows

Status: implemented, 2026-10-06. Decision record: [ADR 0014](../adr/0014-observability.md). Code: [backend/src/synapse/operations/](../../backend/src/synapse/operations/), the routes in [operations_routes.py](../../backend/src/synapse/api/operations_routes.py), the page in [SystemPage.tsx](../../frontend/src/features/admin/SystemPage.tsx).

`GET /api/admin/operations` (permission `operations.view`, administrators) answers in one tenant transaction, from the database, the blob volume the API mounts and the model servers' `/health`, so it works without any observability stack.

| Part | What it is | From |
|---|---|---|
| `services` | The database; the worker and the scheduler, running when they hold a connection (each process names its connections, and another role's session shows its name though not its queries); each model server the API calls, healthy once its model is loaded (3 seconds at most) | `pg_stat_activity`, `/health` |
| `queues` | Per queue: jobs waiting, running and failed, this installation's only | `procrastinate_jobs` |
| `documents`, `deleted_waiting`, `retryable` | Live documents by the status of their latest version; deleted ones not purged yet; those whose processing stopped on an error that may not come again (below) | `documents`, `document_versions` |
| `pages` | Pages of those versions: all, read by OCR, waiting for OCR, needing it but not read (the engines failed on them), with identifiers OCR was unsure of | `document_pages` |
| `storage` | Bytes of uploaded files and of the database; free and total space where the files are | `blobs`, `pg_database_size`, the volume |
| `runs` | The latest run of each kind, and the latest that succeeded: `backup`, `backup_verify`, `files_sweep`, `audit_verify` | `operation_runs` |
| `problems` | The consistency checks of ADR 0003 that are not zero: ready versions without chunks, chunks of ready versions without vectors, documents deleted more than a day ago and not purged, blob rows no version names | live queries |

## Retrying

`POST /api/admin/operations/retry` (permission `operations.manage`, administrators, migration 0023) processes again the newest version of each live document that stopped on an error that may not come again ([processing.py](../../backend/src/synapse/knowledge/processing.py), `retry_failed`): one that failed with `internal_error` (the worker crashed on it after every retry) is parsed again from the start, its pages and chunks removed first; one left without vectors when the embedding model failed gets an embedding job. A file the parser cannot read (`unreadable`, `encrypted`, ...) would fail the same way, and is left as it is. Each version is locked as the jobs lock it, so a running job is never raced. The retry is audited (`ops.documents.retry`, with the counts).

## Runs

`operation_runs` (migration 0022) keeps one row per run: kind, success, start, end and details (counts, or the first line of an error).

- **Backups and their verifications** run on the host ([backup.md](backup.md)); after each, synapsectl runs `synapse operations record` in a one-off API container. A failed run carries a reason the page puts into words (`repository_missing`, `not_configured`, `database_down`, `disk_full`, `audit_differs`, `rows_differ`, `dump_damaged`, or `other`) beside the error's first line. A run that cannot be recorded (the database is down) still counts: `status.json` on the host has it, and `doctor` reads that.
- **The nightly file sweep** (00:40 UTC) records what it removed and whether any blob row has lost its file ([knowledge-base.md](knowledge-base.md#deleting)).
- **The nightly audit verification** (01:20 UTC) recomputes the chain and compares the checkpoints with it, as `synapse audit verify` does ([audit.md](audit.md)), and logs an error when either is broken.

A restored database holds the runs up to its dump, not the backup that restored it.

## Tests

[tests/db/test_operations.py](../../backend/tests/db/test_operations.py) against the real database, queue and roles: the counts after uploads, processing and a delete; a process seen by its connections under another role; a broken invariant reported; backups recorded through the command line, the latest and the latest good one; members refused. The scheduler's records in [tests/db/test_maintenance.py](../../backend/tests/db/test_maintenance.py); synapsectl's in [synapsectl/tests/test_backup.py](../../synapsectl/tests/test_backup.py), where a run that cannot be recorded does not fail.

## The page

Administration, tab "System" (`/admin/system`), from the design approved on 2026-10-06. Everything is said in plain words: the parts of Synapse by what they do (the records, the document reader, the caretaker, the search, ranking and answer helpers), never by their technical names. On top, either "all is well" or the list of what needs attention, the most serious first, each with what it means for the users and what to do:

- a part not running; the audit log found damaged at night;
- no backup yet, the last one failed (with its reason and the last good one), or the last good one more than two days old; a backup check that found a problem;
- files that went missing; documents whose reading stopped halfway (with "Try again" in the documents card); documents not fully searchable, deleted ones not purged, files no document owns;
- less than a tenth of the disk free.

Below: the parts, the documents (ready, being read, could not be read, being deleted; what waits; "Try again"), the scanned pages, the backups, the space, and the audit log's last nightly check. The page asks again every minute, and on "Check again". The documents that could not be read are only counted: an administrator does not always have the right to read them, so their names stay in Documents, where each user sees their own. Checked by the tests in [admin.test.tsx](../../frontend/src/features/admin/admin.test.tsx), and in a browser against a stand-in API, in Turkish and English, wide and at phone width.

## Not done yet

- Sending alerts (email) when a check fails or a backup is late.
- The licence, with modules.
