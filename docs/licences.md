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
| `@fontsource-variable/ibm-plex-sans`, `@fontsource/ibm-plex-mono` | OFL-1.1 | Frontend (the UI typefaces, bundled into the static build) | Allowed: the SIL Open Font License permits bundling and embedding fonts in software, including commercial software; it only forbids selling the font on its own. The licence text ships with the third-party notices |
| `psycopg`, `psycopg-binary`, `psycopg-pool` | LGPL-3.0-only | Backend runtime (database driver; also required by the job queue) | Allowed with conditions, see below |
| `pillow` | MIT-CMU (HPND) | Backend runtime (image support for the Office readers) | Allowed: permissive, OSI-approved; the gate did not know the identifier |
| `pypdfium2` | Apache-2.0 or BSD-3-Clause, with bundled third-party libraries | Backend worker (PDF text extraction) | Allowed with a credit line, see below |
| `antlr4-python3-runtime` | BSD-3-Clause (the ANTLR project's licence); the package metadata says only "BSD" and the wheel carries no licence file | Backend worker (needed by `omegaconf`, RapidOCR's configuration library) | Allowed: permissive |

The gate also learned two things on 2026-09-28, when RapidOCR brought new dependencies: an expression joined by `AND` is allowed only when every part is (`numpy`: BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0; `tqdm`: MPL-2.0 AND MIT), and "3-Clause BSD License" (`protobuf`) is BSD-3-Clause. RapidOCR itself is Apache-2.0, `onnxruntime` MIT, `opencv-python-headless` Apache-2.0.

### Code adapted from React Bits, reviewed 2026-10-02

Four small pieces of the frontend are adapted from [React Bits](https://reactbits.dev) (github.com/DavidHDev/react-bits): `ShinyText`, `BlurText`, `CountUp` and `SpotlightCard`, in `frontend/src/components/reactbits/`. React Bits is not a package dependency; its components are copied into the project, so the licence gate does not see them and this entry records them.

The licence is **MIT with the Commons Clause**, a "source available" licence under ADR 0016. The Commons Clause withholds the right to sell the software itself, that is to offer for a fee a product or service whose value derives entirely or substantially from it; the project states the intent as: the components may be used in commercial applications, but not sold, sublicensed or redistributed as components. Decision: **allowed**, because

1. they are a small part of the interface (a status line, a greeting, counting numbers, a light under the pointer); Synapse's value does not derive from them, and it is not sold as a component library;
2. they are shipped only inside the built application, never as separate components or source a customer could reuse;
3. each file says where it comes from and under which licence, and the licence text goes into the third-party notices.

They use `motion` (MIT). React Bits components that need GSAP (licensed under GSAP's own terms, not MIT) are not used.

### CSS copied from shadcn, reviewed 2026-10-05

`frontend/src/styles/shadcn.css` is the stylesheet of the shadcn package 4.21.0 (`dist/tailwind.css`: animation keyframes, `data-*` variants and the `no-scrollbar`, `scroll-fade` and `shimmer` utilities), copied unchanged. The package is not a dependency, so the licence gate does not see it and this entry records it. The licence is MIT (copyright (c) 2023 shadcn): **allowed**; the file names its source and licence, and the licence text goes into the third-party notices.

### OCR programs and models in the application image, reviewed 2026-09-28 (PP-OCRv6 2026-10-05)

| Component | Source | Licence | Redistribution in the image |
|---|---|---|---|
| Tesseract 5.5 (program and libraries) | Debian package `tesseract-ocr` | Apache-2.0; its libraries (Leptonica and image codecs) permissive | Allowed; Debian's copyright files stay in the image |
| Tesseract `tessdata_best` 4.1.0 `tur` and `eng` | github.com/tesseract-ocr/tessdata_best, pinned by checksum | Apache-2.0 | Allowed |
| PP-OCR detection and Latin recognition models (ONNX) | Converted by the RapidOCR project from PaddleOCR, fetched by RapidOCR 3.9.2 with its own SHA-256 | Apache-2.0 | Allowed |
| PP-OCRv6 detection and Turkish recognition models (`detection.onnx`, `recognition.onnx`, `characters.json`) | PaddleOCR's PP-OCRv6_medium_det and PP-OCRv6_medium_rec, the recogniser fine-tuned for Turkish on synthetic lines (Turkish Wikipedia text in open fonts) and lines of the SCU-CENG Turkish Receipt Dataset (MIT); converted with paddle2onnx 2.1.0; assets of this repository's release `ocr-models-1`, pinned by checksum | Apache-2.0 | Allowed, with the licence |
| Turkish character language model (`charlm.npz`, same release) | 6-gram statistics of 15 million characters of Turkish Wikipedia (`synapse.knowledge.charlm`), stored as hashes and probabilities | CC BY-SA 4.0, as its source text | Allowed, below |

The language model is data the engine reads, not code built with it. CC BY-SA 4.0 asks for attribution and for adaptations of the material to carry the same licence: the file is distributed under CC BY-SA 4.0 with the attribution (the release notes, the third-party notices), and the share-alike does not reach the software that reads it.

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

The model servers' files ([ADR 0018](adr/0018-model-defaults.md)), pinned by SHA-256 in [synapsectl/models.py](../synapsectl/src/synapsectl/models.py), checked 2026-10-01:

| Model | Source | Licence | Redistribution in an appliance |
|---|---|---|---|
| bge-m3 (`bge-m3-q8_0.gguf`, `bge-m3-f16.gguf`) | `BAAI/bge-m3` at `5617a9f6`, converted with llama.cpp b11243 | MIT | Allowed; the licence text ships with the third-party notices |
| bge-reranker-v2-m3 (`bge-reranker-v2-m3-q8_0.gguf`, `-f16.gguf`) | `BAAI/bge-reranker-v2-m3` at `953dc6f6`, converted the same way | Apache-2.0 | Allowed, with the licence and any NOTICE |
| Qwen3.5-4B (`Qwen3.5-4B-Q4_K_M.gguf`) | `unsloth/Qwen3.5-4B-GGUF` at `e87f1764`, a quantisation of `Qwen/Qwen3.5-4B` | Apache-2.0 | Allowed, with the licence and any NOTICE |

The servers run llama.cpp's own images (`ghcr.io/ggml-org/llama.cpp`, build b11243, pinned by digest): llama.cpp is MIT; the images' Ubuntu packages carry their own licences in `/usr/share/doc`, as in any Ubuntu image. Gemma 4, the other chat candidate measured, is Apache-2.0 too, unlike the Gemma releases before it (ADR 0016's "Gemma terms").
