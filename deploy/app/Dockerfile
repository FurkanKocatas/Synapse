# The Synapse application image: one image, several roles (ADR 0002).
#   docker build -f deploy/app/Dockerfile -t synapse-app .
# Base images are pinned by digest; update them deliberately.

ARG PYTHON=python:3.14-slim-trixie@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d
ARG UV=ghcr.io/astral-sh/uv:0.11@sha256:77280f2f771df71f90786c314fe1bbc1e023feac652969bbf139c280babf2eb7

FROM ${UV} AS uv

FROM ${PYTHON} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
# Dependencies first, so code changes do not reinstall them.
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/src ./src
RUN uv sync --locked --no-dev --no-editable
# RapidOCR downloads its models the first time an engine is created (checked against the
# SHA-256 in its package); doing it here means the running containers need no network.
RUN /app/.venv/bin/python -c "from synapse.knowledge.rapid import fetch_models; fetch_models()"

FROM ${PYTHON}
# pip is not needed at run time; removing it also removes the libraries it vendors, which
# otherwise show up in image scans.
RUN python -m pip uninstall --yes pip \
 && groupadd --system --gid 10001 synapse \
 && useradd --system --uid 10001 --gid synapse --no-create-home --shell /usr/sbin/nologin synapse
# Debian security updates published after the base image was built (the image scan fails on
# any HIGH or CRITICAL finding that has a fix), then OCR (docs/benchmarks/ocr.md): Debian's
# Tesseract, with the official "best" Turkish and English models pinned by release and
# checksum (the same files the benchmark measured).
RUN apt-get update \
 && apt-get upgrade --yes --no-install-recommends \
 && apt-get install --yes --no-install-recommends tesseract-ocr \
 && rm -rf /var/lib/apt/lists/*
ADD --checksum=sha256:e0c3338dc17503dc7d335a507c9ae01b2b46cfd07561171e1e1ac55d85e8e438 \
    https://github.com/tesseract-ocr/tessdata_best/raw/4.1.0/tur.traineddata /usr/share/synapse/tessdata/tur.traineddata
ADD --checksum=sha256:8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba \
    https://github.com/tesseract-ocr/tessdata_best/raw/4.1.0/eng.traineddata /usr/share/synapse/tessdata/eng.traineddata
# ADD from a URL leaves files readable by root only; the application runs as 10001.
RUN chmod -R a+rX /usr/share/synapse/tessdata
# PP-OCRv6 with the Turkish character language model gives scanned pages their text (ADR 0019).
# Its model directory is a release of this repository (ocr-models-1), pinned by checksum;
# --chmod, as a chmod afterwards would copy its 227 MB into another layer.
ADD --checksum=sha256:9d58088cce871cd690deae447f860df699f5db1d4e3ef21cc2a3229497e50ea2 --chmod=644 \
    https://github.com/FurkanKocatas/Synapse/releases/download/ocr-models-1/detection.onnx /usr/share/synapse/ppocr/detection.onnx
ADD --checksum=sha256:4ae1ba8a2e91758c67739ced6e9ce781bf8fe07497682418673d53c8d5af364f --chmod=644 \
    https://github.com/FurkanKocatas/Synapse/releases/download/ocr-models-1/recognition.onnx /usr/share/synapse/ppocr/recognition.onnx
ADD --checksum=sha256:e6948b0b16c8d2c1255403b884fb9b3ecc3e5dea0ddafdfebe7276ef41520a08 --chmod=644 \
    https://github.com/FurkanKocatas/Synapse/releases/download/ocr-models-1/characters.json /usr/share/synapse/ppocr/characters.json
ADD --checksum=sha256:f2312bc47859d24537294c3a4fa7ac139458725657ab08a5649c5b731b58d4c5 --chmod=644 \
    https://github.com/FurkanKocatas/Synapse/releases/download/ocr-models-1/charlm.npz /usr/share/synapse/ppocr/charlm.npz
# PP-OCRv5's Latin recogniser, a second voice in the vote of three readings (ADR 0020).
ADD --checksum=sha256:20e6127d910ef10be0d0fe4a49e68d2474b07e83f57600cdd177b3edb561d194 --chmod=644 \
    https://github.com/FurkanKocatas/Synapse/releases/download/ocr-models-2/latin-recognition.onnx /usr/share/synapse/ppocr/latin-recognition.onnx
ADD --checksum=sha256:736f1593b68e36ffc935e557b1452a2cd43267808eb49ee705a90fb0be8d22c0 --chmod=644 \
    https://github.com/FurkanKocatas/Synapse/releases/download/ocr-models-2/latin-characters.json /usr/share/synapse/ppocr/latin-characters.json
# Some BuildKit versions give the directory ADD creates --chmod's mode too (644: nobody but
# root may enter it), so the directory gets its own.
RUN chmod 755 /usr/share/synapse/ppocr
# Uploaded files live on a volume mounted here; creating the directory in the image gives a new
# volume this owner and mode.
RUN install -d -o 10001 -g 10001 -m 0700 /var/lib/synapse/blobs
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SYNAPSE_OCR_TESSDATA_DIR=/usr/share/synapse/tessdata \
    SYNAPSE_OCR_PPOCR_DIR=/usr/share/synapse/ppocr
USER 10001:10001
# The OCR models must be readable by the user the application runs as: an image whose model
# directory was closed to it failed every scanned page, and the smoke test, built elsewhere,
# did not see it.
RUN for model in /usr/share/synapse/ppocr/* /usr/share/synapse/tessdata/*; do test -r "$model" || exit 1; done
ENTRYPOINT ["synapse"]
CMD ["api"]
