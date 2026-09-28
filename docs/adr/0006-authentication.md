# 0006. Authentication: local accounts with server-side sessions

- Status: accepted
- Date: 2026-09-28

## Context

Customers (municipalities, law firms, clinics) need a strong login without Active Directory in v1. The product is a first-party web app on one origin. Common mistakes in comparable products: JWTs that cannot be revoked and carry personal identifiers readable by anyone holding the token, second-factor secrets stored in plain text, and debug flags that can disable the second factor in production.

Research: [04-architecture.md, section 4.1](../research/04-architecture.md).

## Decision

An own, small `identity` package (target about 1,500 lines, fully tested) built on `argon2-cffi`, `pyotp` and `webauthn`.

| Topic | Rule |
|---|---|
| Password hashing | Argon2id, OWASP minimum (m=19 MiB, t=2, p=1), raised after benchmarking on the target CPU while login stays under 250 ms. Parameters stored in the hash; rehash on login when they change |
| Password policy | NIST SP 800-63B-4: at least 15 characters when the password is the only factor, 8 with MFA; accept at least 64 characters, spaces and Unicode; no composition rules; no forced rotation; reject breached passwords (offline list shipped in the bundle) and context words |
| Sessions | 256-bit random token in a `__Host-synapse_session` cookie (`Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/`). Only its SHA-256 is stored. Idle expiry 30 minutes, absolute expiry 12 hours (configurable). Revoked immediately on logout, password change or role change |
| CSRF | `SameSite=Lax` plus a per-session token in a custom header on every state-changing request |
| MFA | TOTP (secret encrypted at rest, recovery codes hashed) and WebAuthn passkeys. **Mandatory for admin roles.** No bypass flag exists in any environment |
| Throttling | Per-account and per-IP exponential backoff from the 5th failure, capped at 15 minutes; no permanent lockout (a DoS vector). Admin notification at 20 consecutive failures. Same throttling on password reset and MFA verification |
| First admin | Created by `synapsectl init` on the box, never through an open web endpoint |
| Tokens | No JWTs in v1. No personal identifiers in cookies |
| Later | OIDC client (`authlib`, PKCE) with IdP group to role mapping; local accounts remain for break-glass administration |

## Consequences

- Revocation is instant and simple.
- Session lookups hit Postgres on each request; cached in-process for a few seconds per token hash.
- We own security-critical code, so it gets the strictest tests in the repository, including tests that failures deny.

## Alternatives considered

- **fastapi-users:** in maintenance mode with a successor announced.
- **JWT access and refresh tokens:** add revocation and key management problems with no benefit for a same-origin first-party app.
- **External identity provider bundled (Keycloak, Authentik):** another heavy stateful service on a 16 GB box; OIDC support covers customers who already run one.
