# v1 scope

Status: accepted, 2026-09-28. Architecture: [docs/adr/](../adr/). Requirements: [vision.md](vision.md).

This is the contract for the first sellable release. Anything not listed here is out of v1.

## Roles

| Role | Can |
|---|---|
| Admin | Manage users, groups, roles, collections and their permissions, settings, models, modules; view the Operations page. Needs a grant to read document content, like everyone else |
| Editor | Upload and manage documents in collections where they have `write`; chat |
| Member | Search and chat over documents they can read |
| Auditor | Read and export the audit log; verify the chain. No document content |

## Features

### Knowledge base

- Collections (folders) with nested collections; grants per collection and per document, to users, groups or roles, with `read`, `write`, `manage`.
- Upload by drag and drop and by folder; up to 100 MB per file by default (configurable). Formats: PDF (born-digital and scanned), DOCX, XLSX, PPTX, PNG/JPEG/TIFF.
- Document versions: uploading a new version replaces the old one in search atomically; history kept.
- Per-document status visible to editors: queued, parsing, OCR, embedding, ready, failed (with a readable reason), low-quality pages.
- Metadata: title, type, date, number, tags; extracted automatically where possible and editable.
- Delete: removed from search immediately; content purged by a background job.
- Document viewer: PDF pages with highlighted cited regions; other formats rendered to PDF for viewing.

### Search and chat

- One entry box. Results arrive in two steps: sources with highlighted passages (seconds), then the generated answer (streamed).
- Every factual sentence in an answer carries a citation to a document and page; clicking opens the viewer at the highlighted region.
- "Not found in your documents" when evidence is insufficient, with possibly related documents.
- Scope: all readable documents, or selected collections or documents.
- Conversations with follow-up questions; history per user; rename and delete.
- Feedback on answers (helpful, wrong source, incomplete, invented), stored for evaluation.
- Table and number questions answered through calculation over extracted tables, citing the table.
- Cancel an answer in progress; queue position shown when the model is busy.

### Identity and security

- Local accounts, NIST-conformant passwords, TOTP and passkeys; MFA mandatory for admins, optional per tenant for others.
- Sessions with idle and absolute expiry; users can see and revoke their own sessions.
- Password reset by an admin (no email dependency in v1) and self-service when SMTP is configured.
- Tamper-evident audit log with viewer, filters, export (CSV and signed JSON) and chain verification.

### Administration

- Users, groups, roles; bulk user import from CSV.
- Model settings: choose among installed models; optional external provider per tenant with PII masking.
- Tenant configuration for Turkish text: synonyms and abbreviations, entity patterns (decision numbers and the like), stop words.
- Operations page: health of every role and model server, queues, failed jobs with retry, ingestion progress, OCR quality summary, disk, backups, licence.

### Installation and operations

- `synapsectl`: `init` wizard, `apply`, `doctor`, `backup`, `restore`, `upgrade`, `support-bundle`.
- Module registry and offline licence; modules can be enabled at install or later.
- Linux (Ubuntu LTS) and WSL2 (Windows 11 22H2+, Windows Server 2025) install guides.
- Offline bundle for air-gapped installs.

### Quality

- Evaluation harness and a Turkish golden set built from the public evaluation corpus (`eval/`), with targets from [ADR 0010](../adr/0010-rag-pipeline.md).
- Benchmarks on the reference machines recorded in `docs/benchmarks/`.

## Non-functional targets

| Area | Target |
|---|---|
| Sources on screen | Within 3 s at P50 on the entry tier |
| Answer on entry tier (16 GB CPU) | First token within 60 s, full answer within 2 min at P50; P95 within 4 min under two concurrent users |
| Answer on a 16 GB GPU | Full answer within 10 s at P50 |
| Ingestion throughput | Reported per tier after benchmarks; 10,000 documents must complete unattended on the entry tier (overnight batches, resumable) |
| Availability | Any single role can crash and restart without affecting login or search |
| Security | No high or critical findings from dependency and image scans at release; OWASP ASVS level 2 as the review checklist |
| Accessibility | WCAG 2.2 AA for the main flows (keyboard navigation, contrast, labels) |
| Localisation | 100% of UI strings in Turkish and English; Turkish casing and formatting correct |

## Explicitly out of v1

- Optional modules (report, specification, translation, calendar): planned in [modules.md](modules.md).
- Website chatbot (widget).
- Active Directory, LDAP, OIDC (OIDC is the first identity addition after v1).
- Connectors that pull from file shares, email servers or other systems (planned after v1; upload only in v1).
- Mobile apps.
- Clinical decision support, public case law search.
