# Optional modules plan

Status: planned, 2026-09-28. None of these are built in v1. This document records what each module is meant to do, what it needs from the core, and the known failure modes to avoid, so the plan is not lost.

Every module follows the module registry in [ADR 0012](../adr/0012-installer-modules-licensing.md): a package under `synapse.modules.<name>` with a manifest, its own migrations branch, its own permissions, lazy-loaded UI routes, and a licence feature flag. A module uses only the core's public APIs and never imports another module.

Rules shared by all generation modules:

- Generation runs as a background job with progress events, not inside an HTTP request.
- Every generated artifact records its inputs: source documents and versions, model, prompt template version.
- Numbers in generated text must be traceable to a source or to a calculation, using the same verification as chat ([ADR 0010](../adr/0010-rag-pipeline.md)).
- Customer-specific content (metrics, templates, wording) comes from tenant configuration, never from code.
- On the CPU tier, generation of long documents is slow; the UI says so and notifies on completion.

## Report generation (`reports`)

**Purpose:** produce a structured report (for example an activity report section, a summary of decisions over a period, a status report) from selected documents or collections, with every figure cited.

**User flow:** choose a report template, choose sources and period, review an outline, generate section by section, edit, export to DOCX and PDF.

**Needs from core:** retrieval with permission filter, typed tables for figures, the verification step, the document viewer for citations, a DOCX/PDF export service.

**Failure modes to avoid:** models inventing numbers when they do arithmetic; one customer's metrics hard-coded; heuristics such as "keep the largest value per year" picking targets instead of realised figures. So: figures only from typed tables or calculations, template-defined metrics in configuration, explicit handling of planned versus realised values.

## Specification drafting (`specifications`)

**Purpose:** draft technical specifications (for example public procurement technical specifications, şartname) from a template, the organization's earlier specifications and applicable regulations, and review a draft for compliance.

**User flow:** choose a template and a reference set, answer guided questions, generate section by section, run a compliance review that reports issues without rewriting the text, export to DOCX.

**Needs from core:** retrieval over a reference collection, section-level generation jobs, a review step that returns findings with citations, DOCX export with the organization's styles.

**Failure modes to avoid:** one instruction applied to every section call, causing repetition; parsers that expect "5" where the model writes "5. Başlık". So: per-section instructions, structured output with schema validation, and tests with real model output.

## Translation (`translation`)

**Purpose:** translate documents and text between Turkish and English (other languages later) while preserving layout for DOCX and PPTX, with a glossary per tenant.

**User flow:** upload or paste, choose target language and glossary, translate, download in the original format.

**Needs from core:** document parsing to structured blocks, a `ChatModel` suitable for translation, glossary storage in tenant configuration, format-preserving writers.

**Notes:** on the CPU tier this is a background job; an external provider is allowed only when the tenant enabled it and the document is not in a "never send externally" collection. An API for programmatic use is limited to admins.

## Calendar (`calendar`)

**Purpose:** reminders and scheduled tasks tied to documents (for example review dates, contract expiry, deadlines extracted from decisions), and a calendar view of them.

**User flow:** create a reminder from a document or answer, or accept a suggested date extracted from a document; see upcoming items; get notified in the app (email when SMTP is configured).

**Needs from core:** entity extraction of dates, the job scheduler, notifications, permissions (a reminder is visible only to users who can read its document).

**Notes:** external calendar integration (CalDAV, Exchange) is a later step and read-only by default.

## Website chatbot (separate discussion)

A public chatbot embedded in a customer's website, answering from a curated public collection. It has a very different threat model (anonymous users, abuse, origin checks, rate limits per visitor, strict content moderation) and may become a separate product that reuses Synapse's retrieval. It is not planned as a module until that discussion happens.

## Later candidates

- Connectors: SMB file shares, IMAP mailboxes, document management system exports, read-only by default.
- OIDC and LDAP sign-in.
- Deep search: multi-step retrieval for multi-document questions (see [ADR 0010](../adr/0010-rag-pipeline.md), alternatives).
- Speech to text for meeting recordings.
