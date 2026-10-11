# 0022. Audit retention: events for a year, a question's text for six months

- Status: accepted (Furkan, 2026-10-11; floors included)
- Date: 2026-10-11

## Context

Furkan decided on 2026-10-07 that audit events are kept for one year and a chat question's text for six months, both configurable ([data.md](../security/data.md)). Today nothing is ever removed: [ADR 0008](0008-audit-log.md) makes the log append-only and hash-chained, a trigger refuses `UPDATE`, `DELETE` and `TRUNCATE` for everyone, signed checkpoints catch a chain rewritten or cut short ([audit.md](../design/audit.md)), and backups carry it off the machine.

Both periods collide with that design:

- **Removing old events** leaves the first remaining event linked to a hash no longer there and the sequence starting above 1, which `synapse audit verify` reports as tampering, as it should when nobody meant it.
- **Removing a question's text** changes its event's details, so its hash and every later link fail.

ADR 0008 already says how retention may run: "only as a separate, audited maintenance role", and names the failure to avoid, "a retention function the application itself can call to drop old records". A process that can delete the log at will defeats the log.

## Decision

1. **A question's text moves out of the hashed event.** An event may carry a text (a `chat.question` event, its question): its details keep `text_sha256` and `text_length`, and the text goes into `audit_texts` (tenant, event ID, text), insert and select only, like the events. The chain covers the hash, so the text cannot be changed unseen, only removed. The auditor's endpoints and exports join the text back while it is there (`text`, None once removed, its hash still in the details); `synapse audit verify` checks every text still present against its hash. Events written before the change keep their text in their details, until they are a year old and go whole.
2. **Old events go from the start of the chain, with an anchor.** Retention removes the events older than the period, oldest first and never from the middle, and in the same transaction appends an `audit.prune` event to the chain with the last removed event's sequence and hash, the count and the cutoff. Verification starts from the newest anchor: the first remaining event must link to the anchor's hash and follow its sequence. Checkpoints for removed events go with them. A removal that did not go through retention leaves no anchor and is reported as before.
3. **Only a role of its own can run it.** A new database role, `synapse_retention`, can execute one function, `audit_prune()`, and nothing else; the function (security definer, owned by the table owner) is the only path past the trigger. The periods come from `audit_settings`, a row only the migrator writes (from `synapse.toml`'s `[audit]` section through `synapsectl`), not from the caller, and the function refuses periods under a floor: 90 days for events, 30 for a question's text.
4. **It runs from the host, as backups do** ([ADR 0021](0021-backups.md)): `synapsectl audit prune` every night, an hour after the backup's time, through a one-shot `retention` container in the rendered compose file's `backup` profile, the only container with the `synapse_retention` password. The API, the worker and the scheduler never hold it.
5. **Defaults:** `[audit] keep_events_days = 365`, `keep_question_days = 183`. Backups keep what they hold for their own six months, so an event can outlive its period by up to that long in the oldest monthly snapshot; data.md says so.

## Consequences

Built on 2026-10-11: migration [0028](../../backend/src/synapse/migrations/versions/0028_audit_retention.py), [chain.py](../../backend/src/synapse/audit/chain.py), [retention.py](../../synapsectl/src/synapsectl/retention.py), tested in [test_audit_retention.py](../../backend/tests/db/test_audit_retention.py) (the prune event's hash, written in SQL, verified by the Python verifier) and [test_retention.py](../../synapsectl/tests/test_retention.py). A backup verification that no longer finds the backup's last event in the live chain accepts it when the retention anchor accounts for it.

- The log keeps proving what it holds: an event removed by retention is accounted for by a chained, signed anchor; any other gap is still evidence.
- A compromised API, worker or scheduler cannot shorten the log, and a compromised host shortens it only to the floors, recorded.
- The auditor's screen and exports show when a question's text was removed by policy, so a missing text is not mistaken for tampering.
- One more secret, role, migration and systemd timer to install, test and document; `doctor` warns when retention has not run for a week.
- A customer who must keep the log longer (a court hold) raises the periods in `synapse.toml`; nothing goes before the configured day.

## Alternatives considered

- **Redact the question in place and re-hash the chain from there.** Rewriting the chain is exactly what the log exists to make evident; a legitimate rewrite and a forged one would look alike.
- **Keep questions only in conversations, not in the audit log.** Users delete conversations, and administrators now can on request; the log is where "who asked what" must stay for its period.
- **Run retention in the scheduler.** It is a long-running process on the application network; the role that can delete audit events would live in it all day. ADR 0008 rules this out.
- **Partition by month and drop partitions.** Partitions do not answer the chain: dropping one still needs an anchor, and a question's text inside a kept partition still cannot be removed. Possible later for speed, not needed at the expected volumes.
