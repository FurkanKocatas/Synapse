# 0016. Dependency and model licence policy

- Status: accepted
- Date: 2026-09-28

## Context

Synapse is a closed commercial product sold on-premise, as appliances and as SaaS, possibly white-labelled by resellers. Several attractive components have licences that forbid this: non-commercial model weights, AGPL code, revenue caps on weights, branding clauses and multi-tenant restrictions.

Research: [00-summary.md, section 6](../research/00-summary.md), [01-market.md, section 2](../research/01-market.md), [02-hardware-inference.md, section 8](../research/02-hardware-inference.md).

## Decision

**Allowed without review:** MIT, BSD, Apache-2.0, ISC, PostgreSQL, Python Software Foundation, MPL-2.0 (file-level copyleft, unmodified use), Unicode, zlib, CC0.

**Needs a written review in `docs/licences.md` before use:** LGPL, MPL-2.0 with modifications, model licences with use policies (Gemma terms, Llama licence), any "source available" licence.

**Not allowed:**

| Component | Reason |
|---|---|
| AGPL-3.0 code (MinerU, PyMuPDF, ParadeDB community) | Network copyleft conflicts with closed SaaS and appliances |
| GPL code linked into the product (Marker) | Copyleft |
| Non-commercial weights (jina embeddings and rerankers, CC BY-NC) | Commercial use forbidden |
| Weights with revenue caps (Surya, Marker models) | Unpredictable licence cost; usable only with a purchased licence |
| Open WebUI | Branding clause above 50 users |
| Dify | Multi-tenant and logo clauses |

**Process**

- CI runs a licence check on Python and JavaScript dependencies and fails on a non-allowed licence.
- Every model shipped in a bundle is listed in `docs/licences.md` with its licence, source and whether redistribution inside an appliance is permitted.
- A component that becomes necessary but is not allowed needs a new ADR, including the cost of a commercial licence.

## Consequences

- Some best-in-class tools (Surya OCR, MinerU tables) are unavailable by default; the `OCR` and `Parser` ports let a licensed engine be added per customer later.
- The licence check prevents accidental inclusion through transitive dependencies.

## Alternatives considered

- **Case-by-case decisions without a policy:** the way incompatible licences slip in.
