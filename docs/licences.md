# Licence reviews

Policy: [ADR 0016](adr/0016-dependency-licence-policy.md). CI enforces it with [tools/check_licences.py](../tools/check_licences.py). This file records every dependency that needed a review, and every model shipped in a bundle.

## Allowed licence identifiers

Allowed without review: MIT, MIT-0, 0BSD, BSD-2-Clause, BSD-3-Clause, ISC, Apache-2.0 (including the LLVM exception), BlueOak-1.0.0, PostgreSQL, PSF-2.0 / Python-2.0, MPL-2.0 (unmodified use), Unicode-3.0, Unlicense, Zlib, CC0-1.0.

The Unlicense is a public-domain dedication with a permissive fallback; it places fewer obligations on us than MIT.

BlueOak-1.0.0 and MIT-0 are permissive licences equivalent in effect to MIT for our use. The LLVM exception only removes attribution obligations for compiled output.

## Reviewed dependencies

| Package | Licence | Scope | Decision |
|---|---|---|---|
| `@lix-js/sdk-*` platform packages | Field missing; parent `@lix-js/sdk` is MIT | Frontend build (via Paraglide) | Allowed: same licence as the parent package |
| `caniuse-lite` | CC-BY-4.0 | Frontend build only (CSS tooling) | Allowed: data used at build time, not shipped as a component |
| `lightningcss` | MPL-2.0 | Frontend build only | Allowed: used unmodified |
| `pathspec` | MPL-2.0 | Python development tooling | Allowed: used unmodified |
| `@fontsource-variable/geist` | OFL-1.1 | Frontend (the UI typeface, bundled into the static build) | Allowed: the SIL Open Font License permits bundling and embedding fonts in software, including commercial software; it only forbids selling the font on its own. The licence text ships with the third-party notices |
| `psycopg`, `psycopg-binary`, `psycopg-pool` | LGPL-3.0-only | Backend runtime (database driver; also required by the job queue) | Allowed with conditions, see below |
| `pillow` | MIT-CMU (HPND) | Backend runtime (image support for the Office readers) | Allowed: permissive, OSI-approved; the gate did not know the identifier |
| `pypdfium2` | Apache-2.0 or BSD-3-Clause, with bundled third-party libraries | Backend worker (PDF text extraction) | Allowed with a credit line, see below |
| `antlr4-python3-runtime` | BSD-3-Clause (the ANTLR project's licence); the package metadata says only "BSD" and the wheel carries no licence file | Backend worker (needed by `omegaconf`, RapidOCR's configuration library) | Allowed: permissive |

The gate also learned two things on 2026-09-28, when RapidOCR brought new dependencies: an expression joined by `AND` is allowed only when every part is (`numpy`: BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0; `tqdm`: MPL-2.0 AND MIT), and "3-Clause BSD License" (`protobuf`) is BSD-3-Clause. RapidOCR itself is Apache-2.0, `onnxruntime` MIT, `opencv-python-headless` Apache-2.0.

### OCR programs and models in the application image, reviewed 2026-09-28

| Component | Source | Licence | Redistribution in the image |
|---|---|---|---|
| Tesseract 5.5 (program and libraries) | Debian package `tesseract-ocr` | Apache-2.0; its libraries (Leptonica and image codecs) permissive | Allowed; Debian's copyright files stay in the image |
| Tesseract `tessdata_best` 4.1.0 `tur` and `eng` | github.com/tesseract-ocr/tessdata_best, pinned by checksum | Apache-2.0 | Allowed |
| PP-OCR detection and Latin recognition models (ONNX) | Converted by the RapidOCR project from PaddleOCR, fetched by RapidOCR 3.9.2 with its own SHA-256 | Apache-2.0 | Allowed |

### pypdfium2 and the PDFium binary, reviewed 2026-09-28

pypdfium2 is Apache-2.0 or BSD-3-Clause. Its wheel bundles a PDFium build and lists every library in it under `dist-info/licenses/`: PDFium (BSD-3-Clause), Abseil and LLVM libc (Apache-2.0), fast_float, lcms, simdutf and the pdfium-binaries build scripts (MIT), libjpeg-turbo (IJG and BSD-3-Clause), OpenJPEG (BSD-2-Clause), libpng (PNG Reference Library licence v2), libtiff (libtiff licence), zlib (zlib), ICU (Unicode licence), Anti-Grain Geometry 2.3 (permissive, notice required) and FreeType (FreeType Project licence, chosen over its GPL-2.0 alternative). All are permissive. Obligations:

1. Keep the notices: the licence files stay in the installed package inside the image, and the offline bundle's third-party notices file will include them.
2. **FreeType credit:** the product documentation must say "Portions of this software are copyright © The FreeType Project (www.freetype.org). All rights reserved." It goes into the about page and the notices file when those exist; until then this entry is the reminder.

### psycopg (LGPL-3.0), reviewed 2026-09-28

psycopg is the PostgreSQL driver for the backend ([ADR 0017](adr/0017-data-access.md)), and Procrastinate ([ADR 0004](adr/0004-job-queue.md)) requires it, so there is no practical permissive alternative. The LGPL allows use by proprietary software that links to the library, provided the library itself stays replaceable. Conditions we follow:

1. psycopg is used **unmodified**, installed as its own package from PyPI. If we ever need a change, it goes upstream or into a separately published fork under the LGPL.
2. Its licence text and a notice (name, version, source location) are shipped with every image and bundle, as part of the third-party notices generated from the SBOM.
3. Nothing prevents a customer from replacing the installed psycopg with another build: no integrity lock on that package inside the image. (The additional "installation information" duty of LGPL-3.0 applies to consumer products; Synapse appliances are sold to organizations, but we do not rely on that distinction.)
4. `psycopg-binary` bundles libpq (PostgreSQL licence) and OpenSSL (Apache-2.0), both allowed.

## Models shipped in bundles

The OCR models in the application image are listed above. Each model added to a bundle gets a row here: name, source, licence, whether redistribution inside an appliance is permitted, and the date checked.
