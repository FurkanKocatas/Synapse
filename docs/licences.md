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

## Models shipped in bundles

None yet. Each model added to a bundle gets a row here: name, source, licence, whether redistribution inside an appliance is permitted, and the date checked.
