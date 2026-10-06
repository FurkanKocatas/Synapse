# OWASP ASVS 5.0, levels 1 and 2: where Synapse stands

Status: first draft, 6 October 2026, read from the code and the design documents at commit 0b339a1, then updated as gaps were fixed. Each requirement was checked against the code; "met" only with the evidence named. It is the review checklist v1-scope.md asks for (Security: OWASP ASVS level 2), to be kept with the code: a change that meets a requirement updates its row.

The requirements' text is OWASP's, not copied here: see the [OWASP Application Security Verification Standard 5.0.0](https://github.com/OWASP/ASVS/tree/v5.0.0/5.0) (CC BY-SA 4.0), by the identifiers below.

| Status | Requirements |
|---|---|
| met | 111 |
| partly | 57 |
| not yet | 12 |
| not applicable | 73 |
| **all, levels 1 and 2** | **253** |

## V1 Encoding and Sanitization

15 met, 1 partly, 11 not applicable.

| Requirement | Level | Section | Status | Evidence | Note |
|---|---|---|---|---|---|
| V1.1.1 | 2 | Encoding and Sanitization Architecture | met | backend/src/synapse/knowledge/documents.py:147-151; backend/src/synapse/knowledge/metadata.py:67-75; backend/src/synapse/identity/service.py:108 | The framework decodes request data once. Inputs are trimmed, case-folded or cut to a base name before validation. No manual unquote or unescape in product code. |
| V1.1.2 | 2 | Encoding and Sanitization Architecture | met | frontend/eslint.config.js:26; frontend/src/features/chat/Markdown.tsx:57; backend/src/synapse/api/document_routes.py:229; docs/adr/0017-data-access.md | Encoding happens at the point of use: React escaping, psycopg parameters, JSON serialisation, header quoting. Data is stored raw, not pre-encoded. |
| V1.2.1 | 1 | Injection Prevention | met | frontend/eslint.config.js:26; frontend/src/features/chat/Markdown.tsx:57; backend/src/synapse/api/document_routes.py:229; backend/src/synapse/api/app.py:121-124 | React escapes output and a lint rule bans raw HTML. Markdown skips HTML. Content-Disposition is percent-encoded. The request ID header is accepted only as a UUID. |
| V1.2.2 | 1 | Injection Prevention | met | frontend/src/features/chat/chatApi.ts (conversationPath); frontend/src/features/chat/pieces.test.ts; frontend/src/features/library/libraryApi.ts:69; frontend/src/features/chat/Markdown.tsx:57 | Filenames and conversation IDs (which come from the address bar's `?c=`) are URL-encoded into API paths, with a test. react-markdown's default filter blocks javascript: links. |
| V1.2.3 | 1 | Injection Prevention | met | backend/src/synapse/api/chat_routes.py:224-225; deploy/web/Caddyfile:27; docs/adr/0011-frontend.md | JSON is built with json.dumps or pydantic, and SSE data is JSON-encoded. There are no inline scripts and CSP is script-src 'self'. |
| V1.2.4 | 1 | Injection Prevention | met | docs/adr/0017-data-access.md; backend/src/synapse/kernel/database.py:69-71; backend/src/synapse/authz/management.py:291; backend/src/synapse/knowledge/documents.py:419-433; backend/src/synapse/dbadmin/bootstrap.py:68 | All values are psycopg parameters. Dynamic identifiers come only from fixed maps, metadata.FIELDS or sql.Identifier. |
| V1.2.5 | 1 | Injection Prevention | met | backend/src/synapse/knowledge/ocr.py:103-130 | The only OS call is Tesseract, run with an argument list, no shell, and file names the app generates. synapsectl runs fixed docker argument lists. |
| V1.2.6 | 2 | Injection Prevention | not applicable | docs/adr/0006-authentication.md | No LDAP. Accounts are local and stored in PostgreSQL. |
| V1.2.7 | 2 | Injection Prevention | not applicable | backend/src/synapse/knowledge/filetypes.py:79-83 | No XPath queries are built from user input. XML is only read by defusedxml and the document-parser libraries. |
| V1.2.8 | 2 | Injection Prevention | not applicable | none | No LaTeX processing anywhere in the product. |
| V1.2.9 | 2 | Injection Prevention | met | backend/src/synapse/chat/verification.py:70; backend/src/synapse/knowledge/metadata.py:117; backend/src/synapse/knowledge/entities.py:58; backend/src/synapse/knowledge/headings.py:61-64 | Dynamic regex parts (answer claims, kind words, tenant language data) go through re.escape. The frontend builds no RegExp from data. |
| V1.3.1 | 1 | Sanitization | not applicable | backend/src/synapse/knowledge/filetypes.py:50-67; frontend/src/features/chat/Markdown.tsx:57 | No WYSIWYG editor or HTML input. Uploads are limited to PDF, images and Office files; model Markdown is rendered with HTML skipped. |
| V1.3.2 | 1 | Sanitization | met | deploy/web/Caddyfile:27; frontend/eslint.config.js | Searches found no eval, exec or new Function in backend or frontend product code. The CSP has no 'unsafe-eval'. |
| V1.3.3 | 2 | Sanitization | met | backend/src/synapse/audit/browse.py (_cell); backend/tests/audit/test_csv.py; backend/src/synapse/knowledge/documents.py:147-151; backend/src/synapse/api/app.py:121-124 | Filenames, request IDs and prompt inputs are bounded and cleaned. The audit CSV export writes a cell that would start a formula (including full-width forms) behind an apostrophe. |
| V1.3.4 | 2 | Sanitization | not applicable | backend/src/synapse/knowledge/filetypes.py:50-67 | SVG uploads are rejected by content detection. Images embedded in documents are never shown to users. |
| V1.3.5 | 2 | Sanitization | met | frontend/src/features/chat/Markdown.tsx:57; deploy/web/Caddyfile:27; docs/adr/0011-frontend.md | Model Markdown is rendered with skipHtml and default URL filtering. CSP blocks external images. No user CSS, XSL or BBCode is accepted. |
| V1.3.6 | 2 | Sanitization | met | backend/src/synapse/kernel/config.py:28,80-84; backend/src/synapse/models/llama.py | Outbound calls go only to configured model servers, with pattern-checked URLs and fixed paths. Gap: compose network is not marked internal. |
| V1.3.7 | 2 | Sanitization | met | backend/src/synapse/chat/talk.py:154-158; backend/src/synapse/chat/answering.py:428,682 | No template engine. Prompts are constant templates filled by str.format arguments, never built from untrusted input. |
| V1.3.8 | 2 | Sanitization | not applicable | backend/pyproject.toml | Python application; no Java or JNDI. |
| V1.3.9 | 2 | Sanitization | not applicable | docs/adr/0003-single-postgres-store.md:33,47 | No memcache or Redis; caching is in-process only. |
| V1.3.10 | 2 | Sanitization | met | backend/src/synapse/chat/talk.py:154-158; backend/src/synapse/chat/answering.py:682 | Format strings are constants and user data is only passed as arguments. No user-controlled format strings found. |
| V1.3.11 | 2 | Sanitization | not applicable | docs/design/identity.md:151 | No outgoing mail. Password reset by email is deliberately not implemented. |
| V1.4.1 | 2 | Memory, String, and Unmanaged Code | not applicable | backend/pyproject.toml; frontend/package.json | Written in memory-safe Python and TypeScript. Native parsers are third-party and run isolated in worker processes. |
| V1.4.2 | 2 | Memory, String, and Unmanaged Code | not applicable | backend/pyproject.toml | No in-house unmanaged code. Python integers cannot overflow. |
| V1.4.3 | 2 | Memory, String, and Unmanaged Code | not applicable | backend/pyproject.toml | No in-house unmanaged code or manual memory management. |
| V1.5.1 | 1 | Safe Deserialization | partly | backend/src/synapse/knowledge/filetypes.py:79-83; backend/tests/test_knowledge_files.py:84 | The API parses [Content_Types].xml with defusedxml, with a test. Worker DOCX/PPTX/XLSX parsing relies on library defaults, not configured or tested here. |
| V1.5.2 | 2 | Safe Deserialization | met | backend/src/synapse/jobs/worker.py:48-52; backend/src/synapse/api/chat_routes.py:54-63 | Only JSON is deserialised, into pydantic models or typed checks. No pickle or yaml in product code; pickle appears only in eval tooling. |

## V2 Validation and Business Logic

6 met, 5 partly.

| Requirement | Level | Section | Status | Evidence | Note |
|---|---|---|---|---|---|
| V2.1.1 | 1 | Validation and Business Logic Documentation | partly | docs/design/identity.md:63; docs/design/knowledge-base.md:30-38,156; docs/design/search.md:18,30; docs/design/answers.md:60 | Rules are documented for passwords, files, metadata, questions, synonyms and scope. Emails, names and titles have none, and there is no single validation spec. |
| V2.1.2 | 2 | Validation and Business Logic Documentation | partly | docs/design/search.md:30; docs/design/identity.md:132,142 | Some combined rules are documented (a phrase in one synonym group, admin not in the MFA list, the last administrator). Coverage is not systematic. |
| V2.1.3 | 2 | Validation and Business Logic Documentation | partly | docs/design/knowledge-base.md:23; docs/design/answers.md:56,76; docs/design/audit.md:54; docs/design/identity.md:51 | Global limits are documented (upload size, chat slots, export cap, login throttles). Per-user limits on questions, uploads or searches are not. |
| V2.2.1 | 1 | Input Validation | partly | backend/src/synapse/api/chat_routes.py:54-63; backend/src/synapse/knowledge/metadata.py:42-88; backend/src/synapse/migrations/versions/0002_identity.py:26-28 | Typed models, Literals, ranges and DB checks are broad. Some free text has length checks only; email format is enforced only by a DB constraint. |
| V2.2.2 | 1 | Input Validation | met | backend/src/synapse/api/admin_routes.py:99-104; backend/src/synapse/knowledge/metadata.py:42; backend/src/synapse/migrations/versions/0005_authorization.py:115 | Validation is enforced in API models, the service layer and DB constraints. Frontend checks are convenience only. |
| V2.2.3 | 2 | Input Validation | met | backend/src/synapse/organization/settings.py:43-62; backend/src/synapse/authz/management.py:282; backend/src/synapse/migrations/versions/0005_authorization.py:115; backend/src/synapse/identity/accounts.py:193 | Synonym groups must not overlap, principal type must match its value, grants need a live document, and one administrator must remain. |
| V2.3.1 | 1 | Business Logic Security | met | backend/src/synapse/api/deps.py:70-96; docs/design/identity.md:5-24; backend/src/synapse/knowledge/processing.py:429-445 | Session levels force password then second factor. Passkey challenges are single-use and session-bound. Document jobs accept only the expected prior statuses. |
| V2.3.2 | 2 | Business Logic Security | met | backend/src/synapse/knowledge/blobs.py:147-153; backend/src/synapse/api/search_routes.py:26-43; backend/src/synapse/audit/browse.py:170-182; backend/src/synapse/identity/throttle.py:9-12 | The documented limits are enforced in code: upload size, question, scope and result limits, export cap, synonym bounds, login throttles. |
| V2.3.3 | 2 | Business Logic Security | met | backend/src/synapse/kernel/database.py:66-72; backend/src/synapse/knowledge/documents.py:234-285 | Each operation runs in one transaction with its audit event and job, and failures roll back. Stray blob files are swept nightly. |
| V2.3.4 | 2 | Business Logic Security | met | backend/src/synapse/knowledge/documents.py:296-299; backend/src/synapse/identity/accounts.py:193-198; backend/src/synapse/identity/repository.py:296-308; backend/src/synapse/chat/answering.py:225 | Row locks protect version numbering and the last-admin check. TOTP steps are claimed atomically. Each document has a job lock, and chat slots are queued. |
| V2.4.1 | 2 | Anti-automation | partly | backend/src/synapse/identity/throttle.py:9-12; backend/src/synapse/chat/answering.py:225-250; backend/src/synapse/api/document_routes.py:105-120 | Login, MFA and password attempts are throttled, uploads capped, chat queued. No per-user rate limits on chat, search, uploads or downloads; no JSON body size limit. |

## V3 Web Frontend Security

17 met, 2 not applicable.

| Requirement | Level | Section | Status | Evidence | Note |
|---|---|---|---|---|---|
| V3.2.1 | 1 | Unintended Content Interpretation | met | backend/src/synapse/api/document_routes.py:224-235; backend/src/synapse/api/audit_routes.py:152-160; deploy/web/Caddyfile:26-34 | Uploads and audit exports are sent as attachments with nosniff. Caddy's deferred site-wide CSP likely overwrites the download's sandbox CSP, but the attachment header still applies. |
| V3.2.2 | 1 | Unintended Content Interpretation | met | frontend/src/features/chat/Markdown.tsx:54-61; frontend/eslint.config.js:18-26; frontend/src/features/chat/DocumentViewer.tsx (PageText); frontend/src/features/chat/PdfPage.tsx:109-115; frontend/src/features/auth/QrCode.tsx:12-30 | React renders all text. A lint rule bans dangerouslySetInnerHTML. Markdown is rendered with skipHtml. The pdf.js text layer and the QR code inject no HTML. |
| V3.3.1 | 1 | Cookie Setup | met | backend/src/synapse/api/deps.py:17; backend/src/synapse/api/auth_routes.py:69-79 | The only cookie is __Host-synapse_session, set with Secure. The frontend sets no cookies. |
| V3.3.2 | 2 | Cookie Setup | met | backend/src/synapse/api/auth_routes.py:78; docs/adr/0006-authentication.md:20-21 | The session cookie uses SameSite=Lax on purpose, and a per-session CSRF header token backs it up. |
| V3.3.3 | 2 | Cookie Setup | met | backend/src/synapse/api/deps.py:17; backend/src/synapse/api/auth_routes.py:71-78; docs/design/identity.md:48 | The cookie has the __Host- prefix and Path=/, with no Domain attribute. |
| V3.3.4 | 2 | Cookie Setup | met | backend/src/synapse/api/auth_routes.py:69-79,114; backend/tests/db/test_api_auth.py:93-99; frontend/src/lib/api.ts:1-5 | HttpOnly is set. The token travels only in Set-Cookie, and a test checks it never appears in a response body. |
| V3.4.1 | 1 | Browser Security Mechanism Headers | met | deploy/web/Caddyfile:26-28 | Caddy sends max-age=31536000 with includeSubDomains on every response of the site block, including proxied API responses. |
| V3.4.2 | 1 | Browser Security Mechanism Headers | not applicable | deploy/web/Caddyfile:1-2; backend/src/synapse/api/app.py:91-109 | There is no CORS. The SPA and API share one origin, and no Access-Control-Allow-Origin header or CORS middleware exists anywhere. |
| V3.4.3 | 2 | Browser Security Mechanism Headers | met | deploy/web/Caddyfile:27 | A global allowlist CSP with script-src 'self', object-src 'none' and base-uri 'none'. |
| V3.4.4 | 2 | Browser Security Mechanism Headers | met | deploy/web/Caddyfile:29; backend/src/synapse/api/document_routes.py:231 | Caddy adds nosniff site-wide, to SPA and API responses alike. File downloads also set it themselves. |
| V3.4.5 | 2 | Browser Security Mechanism Headers | met | deploy/web/Caddyfile:30; frontend/src/features/chat/Markdown.tsx:18 | Referrer-Policy: same-origin is set site-wide. Links written by the model also use rel="noreferrer noopener". |
| V3.4.6 | 2 | Browser Security Mechanism Headers | met | deploy/web/Caddyfile:27 | The site-wide CSP includes frame-ancestors 'none', and it applies to all site responses. |
| V3.5.1 | 1 | Browser Origin Separation | met | backend/src/synapse/api/deps.py:58-67; backend/src/synapse/identity/tokens.py:23-28; frontend/src/lib/api.ts:92; docs/design/identity.md:49 | Every non-safe request with a session needs X-Synapse-CSRF. This is an HMAC of the session token, compared in constant time. |
| V3.5.2 | 1 | Browser Origin Separation | met | backend/src/synapse/api/deps.py:19-22,94-96; backend/src/synapse/api/auth_routes.py:101 | Login happens before any session, so it requires the non-safelisted X-Synapse-Client: web header. That forces a preflight, which is never granted. |
| V3.5.3 | 1 | Browser Origin Separation | met | backend/src/synapse/api/*_routes.py (e.g. document_routes.py:132-310, account_routes.py:44-75, admin_routes.py:117-310) | All state changes use POST, PUT, PATCH or DELETE. GET handlers only read data; some write audit "view" or "export" events. |
| V3.5.4 | 2 | Browser Origin Separation | met | deploy/web/Caddyfile:20; synapsectl/src/synapsectl/render.py:359-362 | Each installation has one application on its own hostname. The SPA and API share that origin on purpose; nothing else is served there. |
| V3.5.5 | 2 | Browser Origin Separation | not applicable | frontend/src (no postMessage or "message" listeners found) | The frontend never uses postMessage or listens for message events. |
| V3.7.1 | 2 | Other Browser Security Considerations | met | frontend/package.json; frontend/index.html; deploy/web/Caddyfile:27 | The frontend is a React 19 SPA with no plugins, applets or Flash. The CSP's object-src 'none' blocks plugin content. |
| V3.7.2 | 2 | Other Browser Security Considerations | met | frontend/src/router.tsx:35-56; frontend/src/features/auth/LoginPage.tsx:32 | Redirects go only to fixed in-app routes, plus Caddy's same-host HTTPS redirect. No redirect goes to another host or a user-supplied target. |

## V4 API and Web Service

2 met, 1 partly, 1 not yet, 6 not applicable.

| Requirement | Level | Section | Status | Evidence | Note |
|---|---|---|---|---|---|
| V4.1.1 | 1 | Generic Web Service Security | met | backend/src/synapse/api/app.py:111-115; backend/src/synapse/api/audit_routes.py:152-160; backend/src/synapse/api/chat_routes.py:162-165; deploy/web/Caddyfile:52 | JSON is sent as application/json and CSV with charset=utf-8. Starlette adds charset to SSE, and Caddy sets types for static files. |
| V4.1.2 | 2 | Generic Web Service Security | not yet | deploy/web/Caddyfile:9-12,20 | Caddy's automatic HTTP-to-HTTPS redirect (308) covers every path, including /api/*, so API requests sent over HTTP are silently redirected. |
| V4.1.3 | 2 | Generic Web Service Security | met | deploy/web/Caddyfile:36-41; synapsectl/src/synapsectl/render.py:180; backend/src/synapse/cli.py:234-235; backend/src/synapse/api/app.py:121-124 | Caddy (no trusted_proxies set) replaces X-Forwarded-* from clients. Uvicorn trusts these headers only from the internal subnet. A client's X-Request-ID is accepted only if it is a UUID. |
| V4.2.1 | 2 | HTTP Message Structure Validation | partly | deploy/web/Dockerfile:19-27; backend/uv.lock (uvicorn 0.54.0, h11 0.16.0, httptools 0.8.0) | Relies on the patched HTTP parsers in Caddy (Go net/http) and uvicorn. I found no explicit configuration or request-smuggling tests. |
| V4.3.1 | 2 | GraphQL | not applicable | backend/src/synapse/api/ (REST only) | There is no GraphQL or other query-language API, only REST JSON endpoints. |
| V4.3.2 | 2 | GraphQL | not applicable | backend/src/synapse/api/ (REST only) | There is no GraphQL, so there is no introspection to disable. |
| V4.4.1 | 1 | WebSocket | not applicable | backend/src/synapse/api/chat_routes.py:162-165; frontend/src/features/chat/sse.ts | There are no WebSockets. The chat streams Server-Sent Events over a fetch POST. |
| V4.4.2 | 2 | WebSocket | not applicable | backend/src/synapse/api/chat_routes.py:162-165 | There are no WebSocket endpoints, so there is no WebSocket handshake. |
| V4.4.3 | 2 | WebSocket | not applicable | backend/src/synapse/api/deps.py:58-67 | There are no WebSockets. Streaming uses the normal cookie session and CSRF check. |
| V4.4.4 | 2 | WebSocket | not applicable | backend/src/synapse/api/chat_routes.py:127-128 | There are no WebSockets, so no dedicated WebSocket tokens exist. |

## V5 File Handling

7 met, 1 partly, 1 not yet.

| Requirement | Level | Section | Status | Evidence | Note |
|---|---|---|---|---|---|
| V5.1.1 | 2 | File Handling Documentation | partly | docs/design/knowledge-base.md:23,28-38,59,102 | Permitted types, size limit, unpacked limits and safe download are documented. Expected extensions and behaviour when a malicious file is detected are not. |
| V5.2.1 | 1 | File Upload and Content | met | backend/src/synapse/knowledge/blobs.py:134-153; backend/src/synapse/kernel/config.py:64; backend/src/synapse/knowledge/parsing.py:52-55 | The body streams to disk with a 100 MB cap (413) after the permission check. Pages, sheet cells and expansion are limited; parsing runs in memory-limited workers. |
| V5.2.2 | 1 | File Upload and Content | met | backend/src/synapse/knowledge/filetypes.py:50-88 (SUFFIXES); backend/src/synapse/knowledge/documents.py (named_for); backend/tests/test_knowledge_files.py; docs/design/knowledge-base.md#file-types | The type comes from magic bytes and Office content types, never the name. A stored name whose extension does not fit its content gets the content's extension added, so downloads open in the right program. |
| V5.2.3 | 2 | File Upload and Content | met | backend/src/synapse/knowledge/parsing.py (_check_package); backend/tests/test_parsing.py; backend/src/synapse/knowledge/filetypes.py:74 | Office zips are refused before parsing above 1 GiB expanded, a 200x ratio or 10,000 members, with tests. Images rely on Pillow's decompression bomb limit. |
| V5.3.1 | 1 | File Storage | met | backend/src/synapse/knowledge/blobs.py:71-73; deploy/web/Caddyfile:43-52; deploy/compose.stack.yml:128,148,167 | Blobs sit on a volume outside the web root, named by hash with no extension, and are served only through the API as attachments. |
| V5.3.2 | 1 | File Storage | met | backend/src/synapse/knowledge/blobs.py:71-73,141; backend/src/synapse/knowledge/documents.py:147-151 | Storage paths come from the tenant UUID and SHA-256, temporary names are random. The user's filename is only cleaned and stored as metadata. |
| V5.4.1 | 2 | File Download | met | backend/src/synapse/api/document_routes.py:205-235; backend/src/synapse/knowledge/documents.py:147-151 | Downloads take no filename input. The server puts the cleaned stored name in an attachment Content-Disposition. |
| V5.4.2 | 2 | File Download | met | backend/src/synapse/api/document_routes.py:229; backend/src/synapse/api/audit_routes.py:155,160 | Filenames use RFC 6266 filename* with percent-encoding, and audit export names are server-generated. There is no ASCII filename= fallback. |
| V5.4.3 | 2 | File Download | not yet | none | No antivirus or malware scanning of uploads in code, deployment or docs. |

## V6 Authentication

16 met, 8 partly, 4 not yet, 7 not applicable.

| Requirement | Level | Section | Status | Evidence | Note |
|---|---|---|---|---|---|
| V6.1.1 | 1 | Authentication Documentation | partly | docs/design/identity.md:51; docs/adr/0006-authentication.md:23; backend/src/synapse/identity/throttle.py:1-15 | Backoff thresholds, cap and "no permanent lockout" are documented. The values are hard-coded, and the docs do not address an attacker repeatedly blocking one account for 15 minutes. |
| V6.1.2 | 2 | Authentication Documentation | partly | docs/design/identity.md:63; docs/research/04-architecture.md:151 | Only categories are named (email name, display name, organization, product). There is no actual documented list of context-specific words or permutations. |
| V6.1.3 | 2 | Authentication Documentation | met | docs/design/identity.md:5-59,140-142 | Password, TOTP, recovery-code and passkey pathways are documented together, with session levels, throttling and which roles must use MFA. |
| V6.2.1 | 1 | Password Security | met | backend/src/synapse/identity/passwords.py:18-19,73-77; backend/src/synapse/identity/service.py:489-493 | At least 15 characters for single-factor accounts, 8 with a second factor. Enforced on create, change and admin reset. |
| V6.2.2 | 1 | Password Security | met | backend/src/synapse/api/account_routes.py:44-59; frontend/src/features/account/AccountPage.tsx:33-103 | Signed-in users change their own password on the account page. |
| V6.2.3 | 1 | Password Security | met | backend/src/synapse/identity/profile.py:60-80; backend/src/synapse/api/account_routes.py:26-28 | The current password is checked (and throttled) before the new one is validated and stored. |
| V6.2.4 | 1 | Password Security | not yet | docs/design/identity.md:65; backend/src/synapse/identity/passwords.py:73-84 | No check against common passwords; only length and context words. The docs list this as an open item. |
| V6.2.5 | 1 | Password Security | met | backend/src/synapse/identity/passwords.py:73-84; backend/tests/identity/test_passwords.py:60-66 | No composition rules. Any characters, including spaces and Unicode, are accepted. |
| V6.2.6 | 1 | Password Security | met | frontend/src/features/auth/LoginPage.tsx:50-56; frontend/src/features/account/AccountPage.tsx:63-88; frontend/src/features/admin/UsersPage.tsx:83-88; frontend/src/features/admin/ResetPanel.tsx:63-68 | Every password input uses type="password". |
| V6.2.7 | 1 | Password Security | met | frontend/src/features/auth/LoginPage.tsx:54; frontend/src/features/account/AccountPage.tsx:68,79; frontend/src/lib/forms.ts:2-5 | Correct autocomplete hints for password managers, and no paste-blocking handlers anywhere. |
| V6.2.8 | 1 | Password Security | met | backend/src/synapse/identity/passwords.py:59-66; frontend/src/lib/forms.ts:2-5 | The password reaches Argon2 unchanged: no trimming, case change or truncation. Passwords over 256 characters are rejected, not cut. |
| V6.2.9 | 2 | Password Security | met | backend/src/synapse/identity/passwords.py:20-22; backend/src/synapse/api/auth_routes.py:28-30 | Passwords up to 256 characters are accepted (the request limit is 1024). |
| V6.2.10 | 2 | Password Security | met | backend/src/synapse/identity/passwords.py:6-8; docs/design/identity.md:63; backend/src/synapse/identity/repository.py:122-127 | No expiry. password_changed_at is recorded but never used to force rotation. |
| V6.2.11 | 2 | Password Security | partly | backend/src/synapse/identity/service.py (create_user); backend/src/synapse/identity/profile.py; backend/src/synapse/identity/accounts.py (reset_password); backend/src/synapse/identity/repository.py (organization_name); backend/tests/db/test_api_admin.py | The email name, display name and organization name are refused in every new password (creation, change, reset), with a test. Product and role names are not. |
| V6.2.12 | 2 | Password Security | not yet | docs/design/identity.md:65; docs/adr/0006-authentication.md:19 | A breached-password check (offline list) is planned but not implemented. |
| V6.3.1 | 1 | General Authentication Security | partly | backend/src/synapse/identity/service.py:144-161,210-225; backend/src/synapse/identity/throttle.py:9-26; backend/tests/db/test_api_auth.py:128-137 | Per-account and per-IP backoff work as documented. The ADR's admin notification after 20 failures is only a log warning. |
| V6.3.2 | 1 | General Authentication Security | met | backend/src/synapse/accounts_cli.py:1-4,98-119; docs/design/identity.md:85-94; backend/src/synapse/migrations/versions/0002_identity.py:21-43 | No seeded accounts. The first admin is created on the server with an email and password the operator chooses. |
| V6.3.3 | 2 | General Authentication Security | partly | backend/src/synapse/identity/repository.py:241-251; backend/src/synapse/organization/settings.py:22-35; docs/product/v1-scope.md:41 | MFA is mandatory only for admins; other roles are optional and off by default. No documented rationale or mitigations beyond longer passwords. |
| V6.3.4 | 2 | General Authentication Security | met | backend/tests/test_route_inventory.py:47-59; backend/src/synapse/api/deps.py:58-102; docs/design/identity.md:26-41 | A test checks every route either needs a session or is explicitly public. The MFA methods share the same level checks and throttle. |
| V6.4.1 | 1 | Authentication Factor Lifecycle and Recovery | not yet | backend/src/synapse/api/admin_routes.py:117-136; backend/src/synapse/identity/accounts.py:122-145 | No system-generated initial secrets. Passwords an admin sets at creation or reset become long-term: they never expire and need no change at first login. |
| V6.4.2 | 1 | Authentication Factor Lifecycle and Recovery | met | backend/src/synapse/migrations/versions/0002_identity.py:21-43; docs/design/identity.md:61-65 | No password hints or security questions in the schema, API or UI. |
| V6.4.3 | 2 | Authentication Factor Lifecycle and Recovery | partly | backend/src/synapse/identity/accounts.py:122-145; docs/design/identity.md:134-136,151 | Only admins can reset; the reset keeps MFA and ends sessions. The admin chooses and knows the password, no change is forced, and there is no self-service reset. |
| V6.4.4 | 2 | Authentication Factor Lifecycle and Recovery | partly | backend/src/synapse/identity/accounts.py:147-162; docs/design/identity.md:135; backend/src/synapse/identity/recovery.py:12-22 | Recovery codes and an admin MFA reset exist. Nothing documents how the admin proves the user's identity before resetting a lost factor. |
| V6.5.1 | 2 | General Multi-factor authentication requirements | met | backend/src/synapse/identity/repository.py:296-330; backend/src/synapse/identity/totp.py:54-69 | Recovery codes are marked used atomically. The TOTP time step is claimed atomically, so the same or an earlier code is rejected. |
| V6.5.2 | 2 | General Multi-factor authentication requirements | not yet | backend/src/synapse/identity/recovery.py:13,30-31; docs/design/identity.md:69 | Recovery codes have 80 bits (under 112) but are stored as unsalted SHA-256, not a salted password hash. |
| V6.5.3 | 2 | General Multi-factor authentication requirements | met | backend/src/synapse/identity/recovery.py:20; backend/src/synapse/identity/totp.py:46-47; backend/src/synapse/identity/passkeys.py:127,228 | Codes and challenges use secrets.token_bytes. TOTP seeds use pyotp.random_base32 (pyotp 2.10, secrets-based per its documentation; library source not read). |
| V6.5.4 | 2 | General Multi-factor authentication requirements | met | backend/src/synapse/identity/recovery.py:12-22 | Recovery codes carry 80 random bits. There are no out-of-band codes. |
| V6.5.5 | 2 | General Multi-factor authentication requirements | partly | backend/src/synapse/identity/totp.py:18-20,64-68 | The TOTP step is 30 seconds, but the one-step window either side accepts a code for up to about 90 seconds. No out-of-band codes exist. |
| V6.6.1 | 2 | Out-of-Band authentication mechanisms | not applicable | docs/design/identity.md:5-24 | No phone or SMS one-time passwords. |
| V6.6.2 | 2 | Out-of-Band authentication mechanisms | not applicable | docs/design/identity.md:5-24,148-151 | No out-of-band authentication (email, SMS or push) is offered. |
| V6.6.3 | 2 | Out-of-Band authentication mechanisms | not applicable | docs/design/identity.md:5-24,148-151 | No code-based out-of-band mechanism exists. |
| V6.8.1 | 2 | Authentication with an Identity Provider | not applicable | docs/adr/0006-authentication.md:26 | No external identity providers. OIDC is planned for a later release. |
| V6.8.2 | 2 | Authentication with an Identity Provider | not applicable | docs/adr/0006-authentication.md:25-26 | No JWT or SAML assertions are consumed; sessions are server-side only. |
| V6.8.3 | 2 | Authentication with an Identity Provider | not applicable | docs/adr/0006-authentication.md:25-26 | No SAML support. |
| V6.8.4 | 2 | Authentication with an Identity Provider | not applicable | docs/adr/0006-authentication.md:26 | No identity provider yet. acr/amr checks will be needed when OIDC is added. |

## V7 Session Management

8 met, 6 partly, 1 not yet, 3 not applicable.

| Requirement | Level | Section | Status | Evidence | Note |
|---|---|---|---|---|---|
| V7.1.1 | 2 | Session Management Documentation | partly | docs/design/identity.md:24; docs/adr/0006-authentication.md:20; backend/src/synapse/kernel/config.py:60-61 | 30-minute idle and 12-hour absolute limits are documented. There is no NIST rationale, and the settings allow up to 24 h idle and 30 days absolute. |
| V7.1.2 | 2 | Session Management Documentation | not yet | backend/src/synapse/identity/service.py:227-256; docs/design/identity.md | No documented limit on concurrent sessions. Each account can have unlimited sessions, with no defined behaviour. |
| V7.1.3 | 2 | Session Management Documentation | not applicable | docs/adr/0006-authentication.md:26 | No federated identity or SSO. |
| V7.2.1 | 1 | Fundamental Session Management Security | met | backend/src/synapse/api/deps.py:58-67; backend/src/synapse/identity/service.py:260-287 | On every request the API hashes the cookie token and looks it up in Postgres. |
| V7.2.2 | 1 | Fundamental Session Management Security | met | backend/src/synapse/identity/tokens.py:15-20; backend/src/synapse/identity/service.py:227-256 | Each sign-in gets a new random reference token. No static API keys are used for user sessions. |
| V7.2.3 | 1 | Fundamental Session Management Security | met | backend/src/synapse/identity/tokens.py:12-16; backend/src/synapse/migrations/versions/0002_identity.py:50 | 256-bit tokens from secrets.token_urlsafe, and the stored hash column is UNIQUE. |
| V7.2.4 | 1 | Fundamental Session Management Security | met | backend/src/synapse/api/auth_routes.py (login); backend/src/synapse/identity/service.py:363-384; backend/tests/db/test_api_auth.py | A new token is issued at login and at each MFA step, and the one it replaces is revoked; signing in again also ends the session cookie the browser already held, with a test. |
| V7.3.1 | 2 | Session Timeout | met | backend/src/synapse/identity/service.py:268-275; backend/src/synapse/kernel/config.py:60; docs/adr/0006-authentication.md:20 | A 30-minute idle timeout (configurable) is enforced server-side for full sessions. Half-signed-in sessions expire after 5 to 15 minutes. |
| V7.3.2 | 2 | Session Timeout | met | backend/src/synapse/identity/service.py:191,268,381; backend/src/synapse/kernel/config.py:61 | A 12-hour absolute expiry is stored for each session and checked on every request. |
| V7.4.1 | 1 | Session Termination | met | backend/src/synapse/identity/service.py:266-275,295-306; backend/src/synapse/api/auth_routes.py:131-136 | Logout and expiry set revoked_at in the database, and revoked sessions are rejected. |
| V7.4.2 | 1 | Session Termination | met | backend/src/synapse/identity/accounts.py:100-106; backend/src/synapse/identity/service.py:272-275 | Disabling an account revokes all its sessions, and status is checked on every request. Accounts can only be disabled, not deleted. |
| V7.4.3 | 2 | Session Termination | partly | backend/src/synapse/identity/profile.py:85-89; backend/src/synapse/identity/passkeys.py:375-394; backend/src/synapse/identity/service.py:434-476 | Password changes and admin resets end other sessions. Adding or removing passkeys, or enrolling TOTP, does not offer to. |
| V7.4.4 | 2 | Session Termination | partly | frontend/src/components/AccountMenu.tsx:102-105; frontend/src/components/TopBar.tsx:76; frontend/src/components/AuthLayout.tsx:26-35 | Sign-out is in the top-bar account menu on every fully signed-in page. The second-factor and enrollment pages have no sign-out. |
| V7.4.5 | 2 | Session Termination | partly | backend/src/synapse/identity/accounts.py:106,143,160; backend/src/synapse/api/admin_routes.py:139-181 | Sessions end only as a side effect of disabling, a role change or a reset. No direct way to end one user's or all users' sessions. |
| V7.5.1 | 2 | Defenses Against Session Abuse | partly | backend/src/synapse/identity/profile.py:73-75; backend/src/synapse/api/passkey_routes.py:69-99,140-147; backend/src/synapse/api/auth_routes.py:159-188 | Changing the password needs the current one. Adding or removing passkeys and enrolling TOTP need no re-authentication. Users cannot change their email. |
| V7.5.2 | 2 | Defenses Against Session Abuse | partly | backend/src/synapse/api/account_routes.py:62-71; backend/src/synapse/identity/profile.py:123-164; frontend/src/features/account/AccountPage.tsx:105-145 | Users can see their sessions and end them one at a time without re-authenticating. There is no "end all" action. |
| V7.6.1 | 2 | Federated Re-authentication | not applicable | docs/adr/0006-authentication.md:26 | No relying-party/identity-provider federation exists. |
| V7.6.2 | 2 | Federated Re-authentication | not applicable | docs/adr/0006-authentication.md:26; backend/src/synapse/api/auth_routes.py:101-114 | No federation. Local sessions are only created when the user submits the login form. |

## V8 Authorization

4 met, 3 partly.

| Requirement | Level | Section | Status | Evidence | Note |
|---|---|---|---|---|---|
| V8.1.1 | 1 | Authorization Documentation | partly | docs/design/authorization.md:5-39,51-67; docs/adr/0007-authorization.md:14-28; docs/design/knowledge-base.md:44-56; docs/design/answers.md:80 | Role permissions, document grants, inheritance, who may create a collection where, and 404 for invisible objects are documented. The summary role table omits permissions.manage and operations.*. |
| V8.1.2 | 2 | Authorization Documentation | partly | docs/design/knowledge-base.md:52; docs/design/identity.md:132; backend/src/synapse/chat/conversations.py:12-13 | Some field rules are documented: which metadata fields are editable, and that admins can change only role and status. No systematic field-level read/write rules by permission or state. |
| V8.2.1 | 1 | General Authorization Design | met | backend/src/synapse/api/deps.py:113-129; backend/src/synapse/authz/checks.py:16-46; backend/src/synapse/migrations/versions/0005_authorization.py:32-44; backend/tests/test_route_inventory.py:47-69 | require() checks the role_permissions table on every request and denies by default. A CI test fails any route without a session guard or an explicit public marker. |
| V8.2.2 | 1 | General Authorization Design | met | backend/src/synapse/knowledge/documents.py:340-368,520-539; backend/src/synapse/chat/conversations.py:133,443-461; backend/src/synapse/identity/profile.py:144-148; backend/src/synapse/authz/management.py (list_collections, create_collection); backend/tests/db/test_api_admin.py | Documents, conversations, sessions and passkeys are checked per object. Non-admins list only the collections they manage and create collections only inside those (another parent is 404), with a test. |
| V8.2.3 | 2 | General Authorization Design | partly | backend/src/synapse/api/document_routes.py:82-91; backend/src/synapse/api/admin_routes.py:77-110; backend/src/synapse/chat/conversations.py:366-391 | Allowlisted request models (extra=forbid) and explicit response views limit fields. No per-field permissions exist, and stored answers stay visible after document access is revoked. |
| V8.3.1 | 1 | Operation Level Authorization | met | backend/src/synapse/api/deps.py:58-129; backend/src/synapse/migrations/versions/0005_authorization.py:153-192; docs/design/authorization.md:71 | Authorization runs in FastAPI dependencies and in SQL functions under row-level security. Frontend route guards only change what is shown; the API makes every decision. |
| V8.4.1 | 2 | Other Authorization Considerations | met | backend/src/synapse/migrations/sql_helpers.py:4-17; backend/src/synapse/kernel/database.py:65-81; backend/tests/db/test_schema_invariants.py:40-63; backend/src/synapse/knowledge/blobs.py:71-73; docs/adr/0005-tenancy.md | Every tenant table has forced row-level security and the tenant is set per transaction. Foreign keys and blob directories are tenant-scoped, and a schema test enforces this. |

## V9 Self-contained Tokens

7 not applicable.

| Requirement | Level | Section | Status | Evidence | Note |
|---|---|---|---|---|---|
| V9.1.1 | 1 | Token source and integrity | not applicable | backend/src/synapse/identity/tokens.py:1-28; docs/adr/0006-authentication.md:25 | No self-contained tokens: sessions are opaque 256-bit random tokens looked up on the server. The planned Ed25519 licence (ADR 0012) is not implemented. |
| V9.1.2 | 1 | Token source and integrity | not applicable | docs/adr/0006-authentication.md:25,37; backend/src/synapse/identity/tokens.py:1-28 | No JWTs or other self-contained tokens, so there are no token signing algorithms to allowlist. |
| V9.1.3 | 1 | Token source and integrity | not applicable | docs/adr/0006-authentication.md:25; backend/src/synapse/audit/browse.py:226-240 | No self-contained tokens and no jku/x5u/jwk headers. Audit export checks use the installation's public key, not one from the file. |
| V9.2.1 | 1 | Token content | not applicable | docs/design/identity.md:20-24; backend/src/synapse/identity/tokens.py:1-28 | No self-contained tokens. Session idle and absolute expiry are enforced on the server from database rows. |
| V9.2.2 | 2 | Token content | not applicable | backend/src/synapse/api/deps.py:70-102 | No self-contained tokens. Each route checks the session level (pending_mfa, enroll_mfa, full) on the server instead. |
| V9.2.3 | 2 | Token content | not applicable | docs/adr/0006-authentication.md:20,25 | No self-contained tokens and no audience concept. The opaque session cookie is host-only (__Host- prefix). |
| V9.2.4 | 2 | Token content | not applicable | docs/adr/0006-authentication.md:25 | The product does not issue self-contained tokens to any audience. |

## V10 OAuth and OIDC

29 not applicable.

| Requirement | Level | Section | Status | Evidence | Note |
|---|---|---|---|---|---|
| V10.1.1 | 2 | Generic OAuth and OIDC Security | not applicable | docs/adr/0006-authentication.md:25-26; docs/design/identity.md:48 | No OAuth or OIDC; an OIDC client is only planned. The session token is in an HttpOnly cookie that JavaScript cannot read. |
| V10.1.2 | 2 | Generic OAuth and OIDC Security | not applicable | docs/adr/0006-authentication.md:26 | No OAuth/OIDC flows, so there are no state, nonce or PKCE values. |
| V10.2.1 | 2 | OAuth Client | not applicable | docs/adr/0006-authentication.md:26 | No OAuth client or code flow is implemented. |
| V10.2.2 | 2 | OAuth Client | not applicable | docs/adr/0006-authentication.md:26 | No OAuth client and no authorization servers are configured. |
| V10.3.1 | 2 | OAuth Resource Server | not applicable | docs/adr/0006-authentication.md:25-26 | Not an OAuth resource server; no access tokens are accepted. |
| V10.3.2 | 2 | OAuth Resource Server | not applicable | docs/adr/0006-authentication.md:25-26 | Not an OAuth resource server; there are no delegated-authorization claims. |
| V10.3.3 | 2 | OAuth Resource Server | not applicable | docs/adr/0006-authentication.md:25-26 | Not an OAuth resource server. Users are identified from server-side session rows. |
| V10.3.4 | 2 | OAuth Resource Server | not applicable | docs/adr/0006-authentication.md:25-26; backend/src/synapse/api/deps.py:70-75 | Not an OAuth resource server. Authentication strength is enforced through server-side session levels instead. |
| V10.4.1 | 1 | OAuth Authorization Server | not applicable | docs/adr/0006-authentication.md:25-26 | The product is not an OAuth authorization server. |
| V10.4.2 | 1 | OAuth Authorization Server | not applicable | docs/adr/0006-authentication.md:25-26 | The product is not an OAuth authorization server and issues no authorization codes. |
| V10.4.3 | 1 | OAuth Authorization Server | not applicable | docs/adr/0006-authentication.md:25-26 | The product is not an OAuth authorization server. |
| V10.4.4 | 1 | OAuth Authorization Server | not applicable | docs/adr/0006-authentication.md:25-26 | The product is not an OAuth authorization server and has no grant types. |
| V10.4.5 | 1 | OAuth Authorization Server | not applicable | docs/adr/0006-authentication.md:25,37 | No refresh tokens exist; ADR 0006 rejects access/refresh tokens. |
| V10.4.6 | 2 | OAuth Authorization Server | not applicable | docs/adr/0006-authentication.md:25-26 | The product is not an OAuth authorization server. |
| V10.4.7 | 2 | OAuth Authorization Server | not applicable | docs/adr/0006-authentication.md:25-26 | No dynamic client registration; the product is not an authorization server. |
| V10.4.8 | 2 | OAuth Authorization Server | not applicable | docs/adr/0006-authentication.md:25,37 | No refresh tokens exist. |
| V10.4.9 | 2 | OAuth Authorization Server | not applicable | docs/adr/0006-authentication.md:25,37 | No refresh or reference access tokens. Users can end their own server-side sessions instead. |
| V10.4.10 | 2 | OAuth Authorization Server | not applicable | docs/adr/0006-authentication.md:25-26 | The product is not an OAuth authorization server and has no clients. |
| V10.4.11 | 2 | OAuth Authorization Server | not applicable | docs/adr/0006-authentication.md:25-26 | The product is not an OAuth authorization server and has no scopes. |
| V10.5.1 | 2 | OIDC Client | not applicable | docs/adr/0006-authentication.md:26 | No OIDC relying party yet; an OIDC client is only planned. |
| V10.5.2 | 2 | OIDC Client | not applicable | docs/adr/0006-authentication.md:26 | No OIDC relying party yet; there are no ID tokens. |
| V10.5.3 | 2 | OIDC Client | not applicable | docs/adr/0006-authentication.md:26 | No OIDC relying party, so no authorization server metadata is consumed. |
| V10.5.4 | 2 | OIDC Client | not applicable | docs/adr/0006-authentication.md:26 | No OIDC relying party; there are no ID tokens. |
| V10.5.5 | 2 | OIDC Client | not applicable | docs/adr/0006-authentication.md:26 | No OIDC back-channel logout. |
| V10.6.1 | 2 | OpenID Provider | not applicable | docs/adr/0006-authentication.md:25-26 | The product is not an OpenID Provider. |
| V10.6.2 | 2 | OpenID Provider | not applicable | docs/adr/0006-authentication.md:25-26 | The product is not an OpenID Provider. |
| V10.7.1 | 2 | Consent Management | not applicable | docs/adr/0006-authentication.md:25-26 | No OAuth authorization server, so there is no consent management. |
| V10.7.2 | 2 | Consent Management | not applicable | docs/adr/0006-authentication.md:25-26 | No OAuth authorization server, so there are no consent prompts. |
| V10.7.3 | 2 | Consent Management | not applicable | docs/adr/0006-authentication.md:25-26 | No OAuth authorization server, so there are no consents to manage. |

## V11 Cryptography

7 met, 7 partly.

| Requirement | Level | Section | Status | Evidence | Note |
|---|---|---|---|---|---|
| V11.1.1 | 2 | Cryptographic Inventory and Documentation | partly | docs/adr/0013-secrets-and-network-security.md:14-26,43; synapsectl/src/synapsectl/secrets.py:1-9; synapsectl/src/synapsectl/render.py:179-184,233-236 | Key generation, storage and per-process separation are documented. No NIST SP 800-57 lifecycle (rotation, expiry, destruction). The audit signing private key is held by both API and scheduler. |
| V11.1.2 | 2 | Cryptographic Inventory and Documentation | partly | docs/installer.md:116-118; docs/adr/0013-secrets-and-network-security.md:16; docs/design/identity.md:47-56; docs/design/audit.md:44 | Secrets are listed and some algorithms are named across several docs. There is no maintained inventory of keys, algorithms, certificates and their permitted uses. |
| V11.2.1 | 2 | Secure Cryptography Implementation | met | backend/pyproject.toml:10-35; backend/src/synapse/identity/totp.py:15; backend/src/synapse/audit/anchor.py:19-20; backend/src/synapse/identity/passwords.py:11 | Uses pyca/cryptography, argon2-cffi, py_webauthn, pyotp, Python hashlib/hmac/secrets and restic. No home-made cryptographic primitives. |
| V11.2.2 | 2 | Secure Cryptography Implementation | partly | backend/src/synapse/identity/passwords.py:3-4,69-70; backend/src/synapse/identity/totp.py:37-43; synapsectl/src/synapsectl/secrets.py:3-5; backend/src/synapse/audit_cli.py:51-52 | Argon2 parameters can be raised through rehash on login. TOTP ciphertexts carry no version or key id, there is no re-encryption or rotation tooling, and verification assumes one signing key. |
| V11.2.3 | 2 | Secure Cryptography Implementation | partly | backend/src/synapse/identity/totp.py:22; backend/src/synapse/audit/anchor.py:56-59; backend/src/synapse/identity/tokens.py:12-24; backend/src/synapse/identity/passkeys.py:131-170 | AES-256, Ed25519, SHA-256 and HMAC-SHA-256 meet 128 bits. WebAuthn algorithms are not pinned, so library defaults apply, likely including RSA (often 2048-bit, about 112 bits). |
| V11.3.1 | 1 | Encryption Algorithms | met | backend/src/synapse/identity/totp.py:15,31-43 | The only application encryption is AES-256-GCM; backups use restic. No ECB or RSA PKCS#1 v1.5 encryption found. |
| V11.3.2 | 1 | Encryption Algorithms | met | backend/src/synapse/identity/totp.py:31-43; docs/adr/0021-backups.md (decision 3) | TOTP secrets use AES-256-GCM. Backups use restic's authenticated AES-256-CTR with Poly1305-AES. TLS is handled by Caddy. |
| V11.3.3 | 2 | Encryption Algorithms | met | backend/src/synapse/identity/totp.py:3-5,37-43 | AES-GCM authenticates TOTP ciphertexts with the user ID as associated data. restic authenticates backup data with Poly1305. |
| V11.4.1 | 1 | Hashing and Hash-based Functions | partly | backend/src/synapse/audit/chain.py:84; backend/src/synapse/identity/tokens.py:19-24; backend/src/synapse/identity/totp.py:51,61 | SHA-256, HMAC-SHA-256 and Ed25519 are used; no MD5. TOTP uses pyotp's default HMAC-SHA-1 (RFC 6238) for authenticator compatibility. |
| V11.4.2 | 2 | Hashing and Hash-based Functions | met | backend/src/synapse/identity/passwords.py:14-16,55-70; docs/adr/0006-authentication.md:18 | Argon2id at m=19 MiB, t=2, p=1 (OWASP minimum). Parameters are stored in each hash and old hashes are rehashed on login. |
| V11.4.3 | 2 | Hashing and Hash-based Functions | met | backend/src/synapse/audit/chain.py:59-84; backend/src/synapse/audit/browse.py:198-247; backend/src/synapse/knowledge/blobs.py:3 | Integrity hashes are SHA-256 (audit chain, export manifest, blob names, bundles) and signatures are Ed25519. 64-bit BLAKE2b is used only for non-security feature hashing. |
| V11.4.4 | 2 | Hashing and Hash-based Functions | partly | backend/src/synapse/dbadmin/scram.py:14-21 | Only password-derived keys are PostgreSQL SCRAM verifiers: PBKDF2-SHA-256 at 4096 iterations, below current guidance (inputs are 256-bit random). restic handles its own KDF. |
| V11.5.1 | 2 | Random Values | partly | backend/src/synapse/identity/recovery.py:3,12-21; backend/src/synapse/identity/tokens.py:12-16; backend/src/synapse/identity/passkeys.py:127,228; synapsectl/src/synapsectl/secrets.py:54-56 | A CSPRNG is used throughout, and sessions, challenges and keys have 256 bits. Recovery codes carry only 80 bits, below the 128-bit minimum. |
| V11.6.1 | 2 | Public Key Cryptography | met | backend/src/synapse/audit/anchor.py:33-59; backend/src/synapse/audit/browse.py:198-240; synapsectl/src/synapsectl/secrets.py:54-56 | Ed25519 signing via pyca/cryptography from a 32-byte CSPRNG seed. py_webauthn verifies WebAuthn signatures, with the algorithm list left at library defaults. |

## V12 Secure Communication

3 met, 3 partly, 2 not yet, 1 not applicable.

| Requirement | Level | Section | Status | Evidence | Note |
|---|---|---|---|---|---|
| V12.1.1 | 1 | General TLS Security Guidance | met | synapsectl/src/synapsectl/render.py:401-409; deploy/web/Caddyfile:22; docs/deployment.md:99 | Nothing overrides the protocols, and Caddy's defaults allow only TLS 1.2 and 1.3, preferring 1.3. deployment.md still lists "TLS configuration" as not done. |
| V12.1.2 | 2 | General TLS Security Guidance | met | synapsectl/src/synapsectl/render.py:401-409; deploy/web/Caddyfile:22 | Caddy/Go default suites are forward-secret ECDHE AEAD only, and Go sets the order. This comes from defaults; nothing is pinned explicitly. |
| V12.1.3 | 2 | General TLS Security Guidance | not applicable | deploy/web/Caddyfile; backend/src/synapse/api/deps.py | Nothing uses mTLS or client-certificate authentication. |
| V12.2.1 | 1 | HTTPS Communication with External Facing Services | met | deploy/web/Caddyfile:9-12,20-22; synapsectl/src/synapsectl/render.py:365-409; docs/deployment.md:41 | The installer always renders an HTTPS site, and the HTTP port only redirects. The plain-HTTP default is for local testing only. |
| V12.2.2 | 1 | HTTPS Communication with External Facing Services | partly | synapsectl/src/synapsectl/config.py:36-53; synapsectl/src/synapsectl/render.py:401-409; docs/installer.md:25 | ACME mode gives a public certificate, but the default is Caddy's internal CA. "Provided" mode uses the customer's own PKI, which may not be publicly trusted. |
| V12.3.1 | 2 | General Service to Service Communication Security | partly | backend/src/synapse/kernel/database.py:34-42; synapsectl/src/synapsectl/render.py:350-356; deploy/web/Caddyfile:37; docs/adr/0013-secrets-and-network-security.md:34 | User traffic and model downloads use TLS. Database, model-server and Caddy-to-API connections are unencrypted on the internal Docker network. |
| V12.3.2 | 2 | General Service to Service Communication Security | partly | synapsectl/src/synapsectl/models.py:230-234; backend/src/synapse/models/llama.py:67-72; backend/src/synapse/kernel/database.py:34-42 | urllib and httpx verify certificates by default. PostgreSQL connections set no sslmode or root certificate, so libpq "prefer" would not verify the server. |
| V12.3.3 | 2 | General Service to Service Communication Security | not yet | deploy/web/Caddyfile:37; synapsectl/src/synapsectl/render.py:350-356 | Caddy-to-API calls and API/worker calls to the model servers use plain HTTP inside the internal network. |
| V12.3.4 | 2 | General Service to Service Communication Security | not yet | deploy/web/Caddyfile:37; synapsectl/src/synapsectl/render.py:350-356 | There is no internal TLS, so no internal CA or pinned self-signed certificates are configured. |

## V13 Configuration

7 met, 6 partly.

| Requirement | Level | Section | Status | Evidence | Note |
|---|---|---|---|---|---|
| V13.1.1 | 2 | Configuration Documentation | partly | docs/adr/0013-secrets-and-network-security.md:28-34; docs/adr/0002-process-topology.md:27-32; docs/deployment.md:20-56; docs/installer.md:25 | Internal flows (database, model servers, Caddy) are documented. There is no single list of external services (ACME, Hugging Face, registries, NAS), and no statement about user-supplied locations. |
| V13.2.1 | 2 | Backend Communication Configuration | partly | synapsectl/src/synapsectl/secrets.py:29-42; backend/src/synapse/dbadmin/bootstrap.py:90-97; synapsectl/src/synapsectl/render.py:312-326,350-356; backend/src/synapse/models/llama.py:67-71 | Each process has its own database role and each model server its own key. All are static passwords or API keys rotated by hand. No short-lived tokens or certificates. |
| V13.2.2 | 2 | Backend Communication Configuration | partly | backend/src/synapse/dbadmin/bootstrap.py:104-109,149-152; backend/src/synapse/dbadmin/roles.py:17-21; synapsectl/src/synapsectl/render.py:104-111,205-222 | Roles are NOSUPERUSER/NOBYPASSRLS and containers are non-root and hardened. But api, worker and scheduler all get synapse_runtime's full table rights, contrary to ADR 0013. |
| V13.2.3 | 2 | Backend Communication Configuration | met | synapsectl/src/synapsectl/secrets.py:54-92; backend/src/synapse/kernel/secrets.py:150-162; docs/adr/0013-secrets-and-network-security.md:16-18; synapsectl/src/synapsectl/doctor.py:107-120 | Every service credential is random and generated per install. A missing or empty secret stops startup. There are no default passwords. |
| V13.2.4 | 2 | Backend Communication Configuration | partly | backend/src/synapse/kernel/config.py:28,80-85; deploy/web/Caddyfile:36-41; synapsectl/src/synapsectl/render.py:256,277; docs/adr/0013-secrets-and-network-security.md:31 | Configuration fixes which endpoints are called. The Docker network is not `internal: true`, so worker, API and model containers have open outbound access, contradicting ADR 0013. |
| V13.2.5 | 2 | Backend Communication Configuration | partly | deploy/web/Caddyfile:36-41; synapsectl/src/synapsectl/render.py:256,264-286 | Caddy proxies only to api:8000 and the API calls only configured model URLs. No server- or firewall-level outbound allowlist; only restic runs with network_mode none. |
| V13.3.1 | 2 | Secret Management | partly | synapsectl/src/synapsectl/secrets.py:1-116; backend/src/synapse/kernel/secrets.py:150-174; .github/workflows/ci.yml:129-132; .dockerignore:10-11; docs/adr/0013-secrets-and-network-security.md:14-20,47 | Secrets are random, mode 0400 files in a 0700 directory, checked by gitleaks and kept out of images. No vault: plaintext files, and rotation or destruction means deleting files by hand. |
| V13.3.2 | 2 | Secret Management | met | synapsectl/src/synapsectl/render.py:184,215,236,329,397; synapsectl/src/synapsectl/secrets.py:34-45,110-116; synapsectl/src/synapsectl/doctor.py:107-120 | Each container mounts only the secrets it uses. Files are owned by the reading uid with mode 0400, and doctor flags wrong owners or modes. |
| V13.4.1 | 1 | Unintended Information Leakage | met | .dockerignore:11; deploy/app/Dockerfile:19-21,68; deploy/web/Dockerfile:40 | .git is excluded from the build context. Images hold only the installed venv and the built SPA, so no source-control metadata is present or served. |
| V13.4.2 | 2 | Unintended Information Leakage | met | backend/src/synapse/kernel/config.py:7-8,34,43-45; backend/src/synapse/api/app.py:91-99; deploy/web/Caddyfile:8 | No debug switch exists, logging defaults to INFO, API docs are off, and the Caddy admin API is off. The SPA is a production build. |
| V13.4.3 | 2 | Unintended Information Leakage | met | deploy/web/Caddyfile:43-53 | file_server runs without browse, and unknown paths fall back to index.html, so no directory listings are exposed. |
| V13.4.4 | 2 | Unintended Information Leakage | met | deploy/web/Caddyfile:36-53; backend/src/synapse/api/*_routes.py (route decorators) | No component implements TRACE: static files serve GET/HEAD and the API defines no TRACE routes. It is not explicitly blocked or tested. |
| V13.4.5 | 2 | Unintended Information Leakage | met | backend/src/synapse/kernel/config.py:43-45; backend/src/synapse/api/app.py:95-98,131-160; backend/tests/test_health.py:41-45; deploy/web/Caddyfile:8,15-18,36; docs/deployment.md:39,41 | API docs are off by default (tested). /healthz and /readyz sit outside /api so are not proxied. Caddy admin is off and the health port is not published. |

## V14 Data Protection

5 met, 2 partly, 2 not yet.

| Requirement | Level | Section | Status | Evidence | Note |
|---|---|---|---|---|---|
| V14.1.1 | 2 | Data Protection Documentation | not yet | docs/ (no classification document); docs/adr/0014-observability.md:14 | Sensitive data (documents, chats, audit events, credentials, personal data) is not listed or classified into protection levels. KVKK appears only in research docs. |
| V14.1.2 | 2 | Data Protection Documentation | not yet | docs/design/audit.md:63; docs/adr/0021-backups.md:65-66; docs/adr/0014-observability.md:14 | No protection requirements per level. Only scattered decisions exist: log content rules, backup encryption and retention, and audit retention still pending. |
| V14.2.1 | 1 | General Data Protection | met | backend/src/synapse/api/deps.py:17-18; backend/src/synapse/api/auth_routes.py:69-79; backend/src/synapse/api/document_routes.py:35,138; deploy/web/Caddyfile (log filter); tools/stack_smoke.sh | Tokens travel in the cookie or a header, credentials and questions in bodies. An upload's file name and title go in the query string, and the access log drops both (checked against a live Caddy and in the stack smoke test). |
| V14.2.2 | 2 | General Data Protection | met | deploy/web/Caddyfile (handle /api/*); backend/src/synapse/api/document_routes.py:233; synapsectl/src/synapsectl/render.py | No caching proxy or application cache, and partial uploads are deleted. The web front marks every API answer no-store unless the route set its own header. |
| V14.2.3 | 2 | General Data Protection | met | deploy/web/Caddyfile:27; frontend/index.html; frontend/package.json; docs/research/04-architecture.md:272 | No analytics, trackers or third-party scripts. CSP limits scripts, connections and images to self, fonts are bundled, and there is no telemetry. |
| V14.2.4 | 2 | General Data Protection | partly | backend/src/synapse/identity/totp.py:1-39; docs/design/identity.md:47; deploy/web/Caddyfile:55-62; synapsectl/src/synapsectl/support.py:1-13 | Individual controls exist: encrypted TOTP secrets, hashed session tokens, log redaction, encrypted backups. None can be checked against protection levels, because none are defined. |
| V14.3.1 | 1 | Client-side Data Protection | partly | frontend/src/components/AccountMenu.tsx:34-38; frontend/src/features/auth/authApi.ts:63-66; frontend/src/App.tsx:15-23; backend/src/synapse/api/auth_routes.py:131-136 | Logout drops the in-memory CSRF token and the cookie. The React Query cache (conversations, documents) is not cleared, there is no Clear-Site-Data, and a failed logout clears nothing. |
| V14.3.2 | 2 | Client-side Data Protection | met | deploy/web/Caddyfile (handle /api/*); backend/src/synapse/api/document_routes.py:233; backend/src/synapse/api/chat_routes.py:166 | Every API response carries Cache-Control: no-store (Caddy sets it where the API did not; checked against a live Caddy). Built assets are cacheable, index.html is no-cache. |
| V14.3.3 | 2 | Client-side Data Protection | met | frontend/src/lib/api.ts:3-14; frontend/src/lib/theme.ts:6-33; frontend/src/components/HistoryButtons.tsx:11,48; frontend/paraglide.options.js:11; backend/src/synapse/api/auth_routes.py:69-79 | Browser storage holds only theme, locale and a history index. The session is an HttpOnly cookie and the CSRF token stays in memory. |

## V15 Secure Coding and Architecture

8 met, 4 partly, 1 not yet.

| Requirement | Level | Section | Status | Evidence | Note |
|---|---|---|---|---|---|
| V15.1.1 | 1 | Secure Coding and Architecture Documentation | not yet | docs/deployment.md:14-16; .github/workflows/ci.yml:151-157,175-184 | CI blocks known or fixable HIGH/CRITICAL vulnerabilities. No documented risk-based remediation time frames or general library update schedule. |
| V15.1.2 | 2 | Secure Coding and Architecture Documentation | partly | .github/workflows/ci.yml:197-217; backend/uv.lock; frontend/pnpm-lock.yaml; docs/deployment.md:14,97; docs/development.md:110 | Each CI run makes SPDX SBOMs per image (kept 90 days), and dependencies are hash-locked. SBOMs are not kept with releases, and there is no trusted-repository policy. |
| V15.1.3 | 2 | Secure Coding and Architecture Documentation | partly | docs/design/answers.md:56; docs/design/knowledge-base.md:23,102,119; docs/adr/0002-process-topology.md:31-32; docs/adr/0004-job-queue.md:21 | Heavy work (chat, OCR, parsing, embedding) is documented with queues, streaming, timeouts and memory limits. No per-user or per-application limits are documented. |
| V15.2.1 | 1 | Security Architecture and Dependencies | partly | .github/workflows/ci.yml:151-157,175-196; docs/deployment.md:14 | Our images and dependencies are gated on known vulnerabilities. llama.cpp images ship with ungated findings, and there are no documented time frames to measure against. |
| V15.2.2 | 2 | Security Architecture and Dependencies | partly | backend/src/synapse/chat/answering.py:225-249; backend/src/synapse/dbadmin/roles.py:17-26; backend/src/synapse/kernel/config.py:64,87; backend/src/synapse/knowledge/parsing.py:52-53; synapsectl/src/synapsectl/render.py:38-42 | Upload size, page, OCR and statement limits and memory caps exist. No per-user limits on chat, search or upload; the chat queue is unbounded; ADR 0002's circuit breaker is missing. |
| V15.2.3 | 2 | Security Architecture and Dependencies | met | deploy/app/Dockerfile:19-21,29; deploy/web/Dockerfile:40; backend/src/synapse/api/app.py:95-98; synapsectl/src/synapsectl/render.py (_SERVER) | Images exclude tests, dev dependencies and pip, and API docs are off. llama-server runs with --no-webui, so its built-in web page is off. |
| V15.3.1 | 1 | Defensive Coding | met | backend/src/synapse/api/admin_routes.py:77-96; backend/src/synapse/api/document_routes.py:49-102; backend/src/synapse/api/audit_routes.py:164-168; backend/src/synapse/api/chat_routes.py:66-111 | Routes return explicit Pydantic view models or narrow dataclasses. Internal fields such as hashes and secrets are never serialized. |
| V15.3.2 | 2 | Defensive Coding | met | backend/src/synapse/models/llama.py (follow_redirects=False); backend/src/synapse/kernel/config.py:27-28,80-85 | Only fixed internal model URLs are called, and the client is told explicitly not to follow redirects. |
| V15.3.3 | 2 | Defensive Coding | met | backend/src/synapse/api/document_routes.py:82-91; backend/src/synapse/organization/settings.py:31-32; backend/src/synapse/api/admin_routes.py:99-110,139-151 | Each action has its own request model with only allowed fields, passed to services explicitly. Settings and metadata models reject extra keys. |
| V15.3.4 | 2 | Defensive Coding | met | deploy/web/Caddyfile:36-41; backend/src/synapse/cli.py:225-236; backend/src/synapse/kernel/config.py:40-42; synapsectl/src/synapsectl/render.py:180; backend/src/synapse/api/deps.py:42-55 | Uvicorn trusts X-Forwarded-For only from the internal subnet; Caddy sets it from the peer. The validated client IP feeds throttling and the audit log. |
| V15.3.5 | 2 | Defensive Coding | met | backend/pyproject.toml:100; .github/workflows/ci.yml:39-40,97-98; frontend/tsconfig.app.json:11; frontend/eslint.config.js:10 | mypy strict, strict TypeScript with ESLint strictTypeChecked, and Pydantic validation on all inputs. The frontend uses === except deliberate == null checks. |
| V15.3.6 | 2 | Defensive Coding | met | frontend/src/features/chat/scope.ts:68; frontend/src/lib/fileKind.tsx:25,53; frontend/src/features/admin/system.ts:104 | No writes with dynamic keys and no deep merges; Map and Set hold dynamic data. A few read-only object-literal lookups with untrusted keys remain. |
| V15.3.7 | 2 | Defensive Coding | met | backend/src/synapse/api/deps.py:58-67; backend/src/synapse/api/document_routes.py:35,132-139; backend/src/synapse/api/chat_routes.py:54-64 | FastAPI binds each parameter to one declared source (path, query, body, cookie, header). The session comes only from the cookie, CSRF only from the header. |

## V16 Security Logging and Error Handling

6 met, 10 partly.

| Requirement | Level | Section | Status | Evidence | Note |
|---|---|---|---|---|---|
| V16.1.1 | 2 | Security Logging Documentation | partly | docs/adr/0014-observability.md:14-16; docs/design/audit.md:5-17,46-63; docs/installer.md; docs/deployment.md (Container hardening); synapsectl/src/synapsectl/render.py (LOGGING) | Spread across ADR 0014, audit.md, installer.md and deployment.md; no single inventory. Container logs rotate (json-file, five files of 10 MB); their access control is the host's. |
| V16.2.1 | 2 | General Logging | partly | backend/src/synapse/audit/chain.py:26-36,59-84; backend/src/synapse/kernel/logging.py:18-25; backend/src/synapse/api/app.py:117-129; backend/src/synapse/api/deps.py (_current_session) | Audit events carry UTC time, actor, IP, action, target and outcome. Application lines carry request_id and, once signed in, user_id; not the job or trace IDs ADR 0014 promises. |
| V16.2.2 | 2 | General Logging | partly | backend/src/synapse/kernel/logging.py:22; backend/src/synapse/audit/chain.py:55-56,107; synapsectl/src/synapsectl/doctor.py (no clock check) | Timestamps are UTC: structlog TimeStamper utc=True, audit rows UTC with microseconds. No time synchronisation (NTP) setup or check found in installer or doctor. |
| V16.2.3 | 2 | General Logging | met | backend/src/synapse/kernel/logging.py:39-47; deploy/web/Caddyfile:55-57; docs/adr/0014-observability.md:14-16; docs/design/audit.md | Processes log only to stdout and the audit table, both documented; Caddy logs to stdout; no other sinks exist (OTLP export not implemented). |
| V16.2.4 | 2 | General Logging | partly | backend/src/synapse/kernel/logging.py:26-30; deploy/web/Caddyfile:55-62; backend/src/synapse/api/app.py:117-129 | API and Caddy emit JSON lines, linked by X-Request-ID; PostgreSQL and llama-server logs are plain text, no trace or job IDs, no log processor shipped. |
| V16.2.5 | 2 | General Logging | partly | backend/src/synapse/identity/service.py:166-177; deploy/web/Caddyfile:57-61; synapsectl/src/synapsectl/support.py:39-96; docs/adr/0014-observability.md:14; backend/tests/test_logging.py | Passwords/tokens not logged; unknown emails hashed; Caddy drops CSRF header; bundle redacts. No classification-based control; promised secret-scan test absent; upload filenames in access logs. |
| V16.3.1 | 2 | Security Events | met | backend/src/synapse/identity/service.py:147-207,318-359,448-474; backend/src/synapse/identity/passkeys.py:256-359; backend/src/synapse/identity/profile.py:90-121; docs/design/audit.md:7-13 | Password login, MFA verify (TOTP, recovery, passkey), enrolment, throttling, logout and password changes audited with outcome; TOTP versus recovery-code use not distinguished. |
| V16.3.2 | 2 | Security Events | partly | backend/src/synapse/api/deps.py (_current_session, require); backend/tests/db/test_api_auth.py; backend/src/synapse/knowledge/documents.py:10-11 | CSRF failures (api.csrf_failed) and missing permissions (api.forbidden) are logged as warnings with the user. A document the user may not read answers 404 like a missing one, unlogged. |
| V16.3.3 | 2 | Security Events | partly | docs/adr/0008-audit-log.md:14; backend/src/synapse/knowledge/documents.py (stored_file); backend/src/synapse/identity/service.py:147-161; backend/src/synapse/api/deps.py | The events ADR 0008 lists are audited, file downloads included (kb.document.download); CSRF failures are logged. Input validation failures (422) are not. |
| V16.3.4 | 2 | Security Events | partly | backend/src/synapse/api/chat_routes.py:155-157; backend/src/synapse/api/app.py:150-159; backend/src/synapse/jobs/worker.py:77-83; backend/src/synapse/scheduler_cli.py:105-109; backend/src/synapse/api/audit_routes.py:74-99 | Unhandled, stream, readiness and job errors and audit-chain breaks are logged; unreadable signing key silently skips checkpoint checks; backend links are plain HTTP. |
| V16.4.1 | 2 | Log Protection | met | backend/src/synapse/kernel/logging.py:26-30; backend/src/synapse/api/app.py:121-126; backend/src/synapse/audit/chain.py:118-138; deploy/web/Caddyfile:58-59; backend/src/synapse/audit/browse.py (_cell) | The JSON renderer escapes control characters; request IDs are accepted only as UUIDs; audit rows are parameterised canonical JSON; the CSV export neutralises formulas. The console format is for development only. |
| V16.4.2 | 2 | Log Protection | partly | backend/src/synapse/migrations/versions/0004_audit.py:42-56; backend/src/synapse/audit/chain.py:155-201; docs/design/audit.md:27-33; backend/src/synapse/api/audit_routes.py:25,81,102 | Audit table: UPDATE/DELETE revoked, immutability triggers, hash chain, signed checkpoints, auditor-only API. Container stdout logs rely on host permissions, no integrity protection. |
| V16.4.3 | 2 | Log Protection | partly | docs/design/audit.md:33,59-61; docs/adr/0014-observability.md:16; docs/adr/0008-audit-log.md:21 | Only nightly encrypted backups carry the audit chain off-box; application logs stay local; OTLP, syslog and checkpoint export are not implemented. |
| V16.5.1 | 2 | Error Handling | met | backend/src/synapse/api/deps.py:26-31; backend/src/synapse/api/app.py:91-99,111-115; backend/src/synapse/api/chat_routes.py:155-157 | Errors return only stable codes; no debug mode; unhandled exceptions get Starlette's generic 500; stream failures send internal_error; API docs off by default. |
| V16.5.2 | 2 | Error Handling | met | backend/src/synapse/models/llama.py:63-106; backend/src/synapse/knowledge/search.py:241-250,284-292; backend/src/synapse/chat/answering.py:556-563,617-629; backend/src/synapse/jobs/worker.py:59-83 | Model calls time out and map to typed errors; search falls back to lexical; chat returns a failed status; jobs retry with backoff. No circuit breaker. |
| V16.5.3 | 2 | Error Handling | met | backend/src/synapse/api/deps.py:1-4,58-67,113-126; backend/src/synapse/audit/chain.py:87-95; docs/adr/0008-audit-log.md:20; backend/src/synapse/jobs/worker.py:77-83 | Session and permission checks deny on any failure without fallback; audit write failure rolls back the action; final job failure marks work failed, not done. |

## V17 WebRTC

7 not applicable.

| Requirement | Level | Section | Status | Evidence | Note |
|---|---|---|---|---|---|
| V17.1.1 | 2 | TURN Server | not applicable | deploy/web/Caddyfile:31; frontend/src (no RTCPeerConnection, getUserMedia or TURN config) | No TURN server: the product has no WebRTC or real-time audio/video; Permissions-Policy blocks camera and microphone. |
| V17.2.1 | 2 | Media | not applicable | deploy/web/Caddyfile:31; frontend/src (no WebRTC code) | No DTLS certificate or media server: the product has no WebRTC media. |
| V17.2.2 | 2 | Media | not applicable | deploy/web/Caddyfile:31; frontend/src (no WebRTC code) | No media server or DTLS-SRTP: the product has no WebRTC media. |
| V17.2.3 | 2 | Media | not applicable | deploy/web/Caddyfile:31; frontend/src (no WebRTC code) | No SRTP/RTP media streams or media server exist in the product. |
| V17.2.4 | 2 | Media | not applicable | deploy/web/Caddyfile:31; frontend/src (no WebRTC code) | No media server processes SRTP packets; the product has no real-time media. |
| V17.3.1 | 2 | Signaling | not applicable | frontend/src (no WebRTC or WebSocket code); backend/src/synapse/api (HTTP and SSE only) | No WebRTC signaling server; chat uses plain HTTP with server-sent events. |
| V17.3.2 | 2 | Signaling | not applicable | frontend/src (no WebRTC or WebSocket code); backend/src/synapse/api (HTTP and SSE only) | No WebRTC signaling server exists to receive malformed signaling messages. |
