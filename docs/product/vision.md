# Product vision and requirements

Status: accepted, 2026-09-28. Owner: Furkan Kocataş.

## Vision

Synapse lets an organization ask questions of its own documents and get correct, cited answers, on hardware it already owns or can buy cheaply, without its data leaving the building.

It is a general product that can be tailored per sector through configuration (document types, entity patterns, synonyms, prompts, retention), not through code.

## Who it is for

| Segment | Typical buyer | Typical documents | Main reason to buy |
|---|---|---|---|
| Municipalities (district, provincial, small metropolitan) | IT manager, deputy mayor for digital transformation | Council and committee decisions, regulations, directives, activity reports, strategic plans, procurement files | Institutional memory in scanned PDFs; KVKK and public-sector data rules forbid foreign cloud AI |
| Law firms (5+ lawyers) | Managing partner | Own petitions, contracts, opinions, correspondence, court file exports | Attorney confidentiality; bar association guidance against sending client data to public AI |
| Healthcare (private hospitals, clinics, medical centres) | Quality manager, IT manager | Procedures, quality standards documents, infection control guides, protocols, training material | Staff find the right procedure quickly; health data is a special category under KVKK |
| SMBs generally | Owner or IT | Contracts, policies, product documents, spreadsheets | Search and answers over scattered files |

Out of scope for v1: clinical decision support (medical device exposure), public case law search (crowded SaaS market; UYAP already summarizes case files), patient records.

## Product principles

1. **Correct before fluent.** An answer is either supported by cited passages or it is a clear "not found in your documents". No invented numbers, ever.
2. **Retrieval first.** Relevant sources with highlighted passages appear within seconds, before and independent of the generated answer. Search alone is useful even on the slowest hardware.
3. **Permissions are part of search.** A user can never retrieve, see or be answered from a document they are not allowed to read.
4. **Everything is accountable.** Who asked what, what was retrieved, who changed which permission: recorded in a tamper-evident log.
5. **Runs where the customer is.** Offline installs, modest hardware, Windows hosts through WSL2, no phone-home.
6. **Small and sound.** A compact codebase with enforced boundaries, tests that actually run, and documentation that matches the code.

## Requirements agreed with the owner

| # | Requirement |
|---|---|
| R1 | Built from scratch, as an independent product, to this repository's standards |
| R2 | English only in code, comments, documentation and commits. The UI switches between Turkish and English, with proper translations from the first release |
| R3 | On-premise is the primary deployment. A SaaS edition is developed from the same codebase, to the same quality |
| R4 | Runs on a CPU-only machine with 16 GB RAM (Ryzen 5 3600 class). Slow is acceptable, unusable is not: a chat answer must never take anywhere near 10 minutes. 32 GB or a GPU is the recommended configuration |
| R5 | Local models by default; external model APIs optional per tenant |
| R6 | Linux with Docker Compose is the primary platform; Windows hosts are supported through WSL2 |
| R7 | Core: knowledge base, chat and RAG at the highest achievable quality; users and roles; per-document permissions; audit log; a strong local login. No Active Directory in v1 |
| R8 | All common document types over time. v1: PDF (born-digital and scanned), DOCX, XLSX, PPTX. Comfortable up to 10,000 documents on the CPU tier |
| R9 | Optional modules, selectable by the vendor's installer at setup: report generation, specification drafting, translation, calendar. Planned, not built in v1 (see [modules.md](modules.md)) |
| R10 | The website chatbot (widget) is discussed separately and may become its own product |
| R11 | Failures are isolated (one part failing does not stop the rest) and every part is logged and traceable |
| R12 | Scalability, performance, end-user quality and documentation are good enough to support future TÜBİTAK and KOSGEB applications |

## Hardware tiers

| Tier | Hardware | Expected use |
|---|---|---|
| Entry | CPU only, 16 GB RAM | 5 to 10 named users, 1 to 2 answers at a time, answers in 1 to 2 minutes |
| Recommended | CPU only, 32 GB RAM, or any 8 GB+ GPU | Same users with better models (32 GB) or answers in about 30 seconds (GPU) |
| Performance | 16 GB+ GPU | 10 to 25 concurrent users, answers in under 10 seconds |

Benchmark reference machines: a Ryzen 5 3600 class desktop (the minimum target) and a Chuwi mini PC with a Ryzen 5 6600H and 16 GB DDR5 (available to the team). The 6600H is faster than the 3600 (Zen 3+, DDR5 bandwidth), so results on it are scaled down when stated for the minimum target, and the 3600 figure is confirmed on real hardware before it is promised to a customer.

## Naming

"Synapse" is a working name. The market research found high trademark risk (Azure Synapse, Matrix Synapse, and Fujifilm Synapse, a healthcare IT product sold in Turkey). A distinctive product name will be chosen before any public use.
