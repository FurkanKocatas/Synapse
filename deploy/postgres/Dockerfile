# PostgreSQL 18 with pgvector (vectors, HNSW) and pg_textsearch (BM25), per ADR 0003.
# Both the base image and the extension source are pinned; update them together and record the
# change in the commit message.

ARG BASE=pgvector/pgvector:0.8.6-pg18-trixie@sha256:78bf48b801e792f99e3ac62b5036fd3876e9be48afda16c1e331af1c75ceb2ff

FROM ${BASE} AS build
ARG PG_TEXTSEARCH_COMMIT=7a932505b537d50ad8d2d068a053cd1dd7b646ea  # v1.4.0
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential ca-certificates git postgresql-server-dev-18 \
 && rm -rf /var/lib/apt/lists/*
RUN git clone --filter=blob:none https://github.com/timescale/pg_textsearch.git /src \
 && git -C /src checkout --detach "${PG_TEXTSEARCH_COMMIT}" \
 && make -C /src \
 && make -C /src install DESTDIR=/out

FROM ${BASE}
COPY --from=build /out/usr/lib/postgresql/18/lib/ /usr/lib/postgresql/18/lib/
COPY --from=build /out/usr/share/postgresql/18/extension/ /usr/share/postgresql/18/extension/
# pg_textsearch must be preloaded. Further settings are passed by the deployment (synapsectl
# renders them per hardware tier), so only what the extension requires is fixed here.
CMD ["postgres", "-c", "shared_preload_libraries=pg_textsearch"]
