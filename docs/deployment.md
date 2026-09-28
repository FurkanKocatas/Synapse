# Deployment: images and the full stack

Status: 2026-09-28. Customer installations get their compose file from `synapsectl render` ([installer.md](installer.md)); `deploy/compose.stack.yml` is the same stack for local tests, built from this repository.

## Images

| Image | Built from | Runs as | Contents |
|---|---|---|---|
| `synapse-app` | [deploy/app/Dockerfile](../deploy/app/Dockerfile) | uid 10001 | Python 3.14 and the backend, installed from `uv.lock` without development dependencies. One image for every role (`synapse api`, `synapse worker`, `synapse db migrate`, ...). The worker runs as its own database role and mounts the blob volume read-only. OCR ([benchmark](benchmarks/ocr.md)): Debian's Tesseract with the official "best" Turkish and English models pinned by checksum, and RapidOCR's models fetched at build time, so the containers need no network. The worker's memory limit is 2.5 GB on the 16 GB tier, since OCR peaks at about 2 GB. pip is removed |
| `synapse-web` | [deploy/web/Dockerfile](../deploy/web/Dockerfile) | uid 10001 | The built SPA and Caddy, which serves it and proxies `/api`. Caddy is compiled from source with a current Go toolchain and patched modules |
| `synapse-postgres` | [deploy/postgres/Dockerfile](../deploy/postgres/Dockerfile) | postgres (999) | PostgreSQL 18 with pgvector and pg_textsearch, Debian security updates applied, gosu removed |

Every base image is pinned by digest. CI builds all three and fails on any HIGH or CRITICAL vulnerability that has a fix ([Trivy](https://trivy.dev), `--ignore-unfixed`).

Why Caddy is rebuilt: the published Caddy 2.11.4 binary was built with Go 1.26.3 and older `golang.org/x` and gRPC modules, which the scan reports (17 HIGH findings on 2026-09-28). Building the same Caddy version with Go 1.26.8 and current modules removes all of them. When the scan fails again, bump the versions in the Dockerfile.

Why gosu is gone: the official PostgreSQL entrypoint uses gosu to drop from root to `postgres`. Starting the container as `postgres` makes that step unnecessary, so the binary (the scan's largest finding) is removed and the database never runs as root.

## Container hardening

Applied in [deploy/compose.stack.yml](../deploy/compose.stack.yml) and required for customer installs:

- Read-only root file systems, with `tmpfs` only where a process must write (`/tmp`, Caddy's `/data` and `/config`).
- `cap_drop: [ALL]` and `no-new-privileges` on the application and web containers.
- Memory limits per container ([ADR 0002](adr/0002-process-topology.md)).
- One internal network. Only the web front publishes a port, bound to loopback in the test stack. The API trusts `X-Forwarded-For` only from the internal subnet.
- Secrets as files under `/run/secrets`, one per purpose ([ADR 0013](adr/0013-secrets-and-network-security.md)).
- Health checks on every long-running service; one-shot `bootstrap` and `migrate` must succeed before the API starts.

## Web front

[deploy/web/Caddyfile](../deploy/web/Caddyfile):

- `/api/*` goes to the API with response buffering off, so streamed answers arrive as they are generated.
- Everything else is the SPA: files from the build, and `index.html` for any other path so deep links work.
- Headers: a strict Content Security Policy (`script-src 'self'`, `style-src 'self'`, no inline code), HSTS, `nosniff`, `Referrer-Policy: same-origin`, a restrictive `Permissions-Policy`, `Cross-Origin-Opener-Policy`, and no `Server` header.
- Caching: hashed files under `/assets/` for a year; pages always revalidated, so a new release is picked up on the next visit.
- The API documentation is not reachable (off in the API, see [development.md](development.md)).

The default site address is plain HTTP on port 8080 inside the container, for local testing only. Customer installs set `SYNAPSE_SITE_ADDRESS` and `SYNAPSE_HTTP_PORT`, and mount a TLS snippet into `/etc/caddy/site.d/` (customer certificate, ACME or Caddy's internal CA), all rendered by `synapsectl`. Port 8099 answers the container health check and is never published.

## Running the full stack locally

```bash
python3 tools/dev_secrets.py
docker compose -f deploy/compose.stack.yml up -d --wait db
docker compose -f deploy/compose.stack.yml run --rm bootstrap
docker compose -f deploy/compose.stack.yml run --rm migrate
docker compose -f deploy/compose.stack.yml run --rm --no-deps -T api tenant create --slug demo --name "Demo"
echo "SYNAPSE_TENANT_ID=<printed id>" > .dev/stack.env
docker compose -f deploy/compose.stack.yml run --rm --no-deps api user create --email you@example.org --name "You" --role admin
docker compose -f deploy/compose.stack.yml up -d --wait
```

Open http://localhost:8480 (`SYNAPSE_STACK_PORT` changes the port, `SYNAPSE_STACK_SUBNET` the internal network).

## End-to-end smoke test

[tools/stack_smoke.sh](../tools/stack_smoke.sh) does the above in a throwaway compose project with its own port and subnet:

1. Builds the images and starts a fresh database.
2. Runs bootstrap and migrations.
3. Creates a tenant and an account with the CLI.
4. Checks the SPA, the security headers and a sign-in through the web front.
5. Registers a passkey and signs in with it through the web front ([tools/smoke_passkey.py](../tools/smoke_passkey.py), with the backend tests' software authenticator), which also proves `SYNAPSE_PUBLIC_URL` reaches the API.
6. Uploads a PDF as an editor, lists it and downloads it byte for byte, which proves the blob volume is writable under the read-only container; then waits for the worker to mark it `parsed` and finds its text in the database.
7. Uploads a scanned PDF (an image only) and waits for OCR: both engines read it in the read-only worker container, which proves the models are in the image and nothing is downloaded at run time; the page must come back as OCR text with the date and decision number in it.
8. Verifies the audit chain.

It then removes everything it created. CI runs it on every push.

## Not done yet

- Backups, upgrades and the offline bundle ([installer.md](installer.md)).
- The scheduler role (periodic jobs such as audit checkpoints and cleanup), and separate workers per queue on bigger machines.
- Image signing and SBOMs in a release workflow.
- TLS configuration and a production memory profile per hardware tier.
