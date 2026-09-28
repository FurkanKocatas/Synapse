# The web front: the built single-page app served by Caddy, which also proxies /api (ADR 0011).
#   docker build -f deploy/web/Dockerfile -t synapse-web .

ARG NODE=node:24-trixie-slim@sha256:8ec5d7557396cfe32d21c3f9c13072355ceab22b584578ca4bb28af31120cffe
ARG CADDY=caddy:2.11-alpine@sha256:6aeddd44c3078b0f9a35206472a11420648a79c184603ef95957d0a20044cb2b
ARG GO=golang:1.26.8-alpine3.24@sha256:8ac98ca534ac3f51e1f420a1dd2c15e74c75cfa0f23f3ad27eb5d7236c349a0c

FROM ${NODE} AS build
RUN corepack enable
WORKDIR /src
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/.npmrc ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# Caddy is rebuilt from source with a current Go toolchain and patched dependencies: the
# published binary lags behind security fixes in Go and in its modules, which the image scan in
# CI reports. Bump these together with CADDY_VERSION when the scan asks for it.
FROM ${GO} AS caddy
ARG CADDY_VERSION=v2.11.4
ARG XCADDY_VERSION=v0.4.7
RUN go install github.com/caddyserver/xcaddy/cmd/xcaddy@${XCADDY_VERSION}
RUN CGO_ENABLED=0 xcaddy build ${CADDY_VERSION} --output /caddy \
      --replace golang.org/x/crypto=golang.org/x/crypto@v0.57.0 \
      --replace golang.org/x/net=golang.org/x/net@v0.59.0 \
      --replace golang.org/x/text=golang.org/x/text@v0.42.0 \
      --replace google.golang.org/grpc=google.golang.org/grpc@v1.84.0

FROM ${CADDY}
# Our build has no file capabilities (the stock binary asks for the right to bind ports below
# 1024, which the kernel refuses once all capabilities are dropped). We listen on 8080.
COPY --from=caddy /caddy /usr/bin/caddy
# /data holds Caddy's certificates (including its internal CA) and must persist; /config
# holds the running configuration. Both belong to the unprivileged user.
RUN addgroup -S -g 10001 synapse \
 && adduser -S -D -H -u 10001 -G synapse synapse \
 && mkdir -p /data /config /etc/caddy/site.d \
 && chown 10001:10001 /data /config
COPY deploy/web/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/dist /srv
USER 10001:10001
