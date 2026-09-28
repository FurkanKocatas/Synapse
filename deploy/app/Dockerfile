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

FROM ${PYTHON}
# pip is not needed at run time; removing it also removes the libraries it vendors, which
# otherwise show up in image scans.
RUN python -m pip uninstall --yes pip \
 && groupadd --system --gid 10001 synapse \
 && useradd --system --uid 10001 --gid synapse --no-create-home --shell /usr/sbin/nologin synapse
# Uploaded files live on a volume mounted here; creating the directory in the image gives a new
# volume this owner and mode.
RUN install -d -o 10001 -g 10001 -m 0700 /var/lib/synapse/blobs
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER 10001:10001
ENTRYPOINT ["synapse"]
CMD ["api"]
