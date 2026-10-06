# The data Synapse holds, and how each kind is protected

Status: 6 October 2026. The classification OWASP ASVS asks for (V14.1.1, V14.1.2; [asvs.md](asvs.md)), and the starting point for an organisation's KVKK records: what is kept, where, who can read it and for how long. A change that adds a kind of data, or changes where or how long it is kept, updates this page.

## Levels

| Level | What it means | Kinds |
|---|---|---|
| Secret | Its leak opens everything else | The installation's secrets, the backup password |
| Restricted | The organisation's content and what people asked of it; may hold personal data | Documents and everything made from them, conversations, the audit log, backups |
| Internal | Accounts and the running of the system | Accounts and their credentials, sessions, settings, application logs |

What each level requires:

- **Secret:** made by a cryptographic random generator for each installation (`synapsectl init`); never in an image, the repository (gitleaks in CI) or a log; a file of mode 0400 readable only by the process that uses it ([installer.md](../installer.md)). Rotation is by hand for now.
- **Restricted:** read only through the permission checks in the database (forced row-level security per tenant, and `accessible_documents` for documents); every read of a document audited; never written to a log; encrypted on the network (TLS at the web front) and in backups. Synapse does not encrypt it on the host's disk: the operator turns on full-disk encryption where the organisation requires it. Removed when deleted, except from backups and the audit log (below).
- **Internal:** credentials stored only as hashes or encrypted; read by administrators within their permissions; personal data in logs limited to user IDs and IP addresses.

## What is kept

| Data | Level | Where | Who can read it | Protection | Kept until |
|---|---|---|---|---|---|
| Uploaded files | Restricted | The blob volume, named by SHA-256 under the tenant's directory | Users with `read` on the document: download and page views, both audited | Served only as attachments with a sandbox CSP; deduplicated only within a tenant | The document is deleted: the purge removes each file no other live document uses ([knowledge-base.md](../design/knowledge-base.md#deleting)) |
| Text, chunks, vectors, entities and details of documents | Restricted | PostgreSQL | The same `read` grants | Row-level security; search filters by `accessible_documents` before ranking | The same purge |
| Conversations: questions, answers, scope, feedback | Restricted | PostgreSQL | Only the user who started each one | Every query filters on that user; sources are kept as references and their text is read again under the user's current permissions | The user deletes the conversation (the rows are deleted). An answer stays when a document it cited is deleted; the source then shows without text or title |
| Audit events: actor, IP address, action, target, outcome, details (a chat question's text, the documents retrieved and cited, the answer's SHA-256 but not its text) | Restricted | PostgreSQL, append-only (UPDATE and DELETE revoked, triggers), hash-chained, with signed checkpoints | The auditor role (`audit.read`); exports are audited | Tampering is evident ([audit.md](../design/audit.md)) | Kept; a retention period is not set yet |
| Backups: the database dump, the uploaded files, `synapse.toml` and the secrets | Restricted | The restic repository, a directory on the host (a NAS share or a disk) | Whoever holds `backup_password` | restic: AES-256 with Poly1305 | 7 daily, 4 weekly and 6 monthly snapshots ([ADR 0021](../adr/0021-backups.md)) |
| Accounts: email, display name, role, language | Internal | PostgreSQL | Administrators (`users.manage`); each user their own | Row-level security | Accounts are disabled, not deleted |
| Credentials | Internal | PostgreSQL | Nobody: only verified | Passwords Argon2id; TOTP secrets AES-256-GCM bound to the user; passkeys as public keys; recovery codes and session tokens as SHA-256 ([identity.md](../design/identity.md)) | Replaced, reset or removed with the factor |
| Sessions: device, IP address, last use | Internal | PostgreSQL | The user (account page) | The token itself is never stored | Ended at sign-out, after 30 minutes idle or 12 hours |
| Settings and synonyms | Internal | PostgreSQL | Administrators (`settings.manage`); every change audited | | Until changed |
| Application and access logs | Internal | Container output, Docker's `json-file` on the host | The host's administrators; the support bundle, redacted ([installer.md](../installer.md#support-bundle)) | No passwords, tokens, document text or questions; the access log drops the CSRF header, upload names and titles, and download names | Rotated: five files of 10 MB per container |
| Secrets | Secret | Files under the secrets directory on the host, each mounted only into the containers that use it | Root on the host | Random per installation, mode 0400 | Until rotated by hand |

## Open decisions

- How long the audit log is kept, and whether a question's text should stay in it for that long.
- Whether a conversation's answers should go when a document they cite is deleted.
- Whether backups keep six months.
- A person's own data on request (KVKK article 11): finding and exporting or deleting one person's conversations and audit entries is not a feature yet.
- Encryption on the host's disk: the installer does not check for it.
