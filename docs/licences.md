# Licence reviews

Policy: [ADR 0016](adr/0016-dependency-licence-policy.md). CI enforces it with [tools/check_licences.py](../tools/check_licences.py). This file records every dependency that needed a review, and every model shipped in a bundle.

## Allowed licence identifiers

Allowed without review: MIT, MIT-0, 0BSD, BSD-2-Clause, BSD-3-Clause, ISC, Apache-2.0 (including the LLVM exception), BlueOak-1.0.0, PostgreSQL, PSF-2.0 / Python-2.0, MPL-2.0 (unmodified use), Unicode-3.0, Zlib, CC0-1.0.

BlueOak-1.0.0 and MIT-0 are permissive licences equivalent in effect to MIT for our use. The LLVM exception only removes attribution obligations for compiled output.

## Reviewed dependencies

| Package | Licence | Scope | Decision |
|---|---|---|---|
| `@lix-js/sdk-*` platform packages | Field missing; parent `@lix-js/sdk` is MIT | Frontend build (via Paraglide) | Allowed: same licence as the parent package |
| `caniuse-lite` | CC-BY-4.0 | Frontend build only (CSS tooling) | Allowed: data used at build time, not shipped as a component |
| `lightningcss` | MPL-2.0 | Frontend build only | Allowed: used unmodified |
| `pathspec` | MPL-2.0 | Python development tooling | Allowed: used unmodified |
| `psycopg`, `psycopg-binary`, `psycopg-pool` | LGPL-3.0-only | Backend runtime (database driver; also required by the job queue) | Allowed with conditions, see below |

### psycopg (LGPL-3.0), reviewed 2026-09-28

psycopg is the PostgreSQL driver for the backend ([ADR 0017](adr/0017-data-access.md)), and Procrastinate ([ADR 0004](adr/0004-job-queue.md)) requires it, so there is no practical permissive alternative. The LGPL allows use by proprietary software that links to the library, provided the library itself stays replaceable. Conditions we follow:

1. psycopg is used **unmodified**, installed as its own package from PyPI. If we ever need a change, it goes upstream or into a separately published fork under the LGPL.
2. Its licence text and a notice (name, version, source location) are shipped with every image and bundle, as part of the third-party notices generated from the SBOM.
3. Nothing prevents a customer from replacing the installed psycopg with another build: no integrity lock on that package inside the image. (The additional "installation information" duty of LGPL-3.0 applies to consumer products; Synapse appliances are sold to organizations, but we do not rely on that distinction.)
4. `psycopg-binary` bundles libpq (PostgreSQL licence) and OpenSSL (Apache-2.0), both allowed.

## Models shipped in bundles

None yet. Each model added to a bundle gets a row here: name, source, licence, whether redistribution inside an appliance is permitted, and the date checked.
