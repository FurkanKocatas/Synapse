# Installer: synapsectl

Status: first version (init, render, doctor), 2026-09-28. Decision record: [ADR 0012](adr/0012-installer-modules-licensing.md). Code: [synapsectl/](../synapsectl/).

`synapsectl` runs on the customer's machine, operated by the vendor's installer. One file, `/etc/synapse/synapse.toml`, describes the installation; everything else is produced from it.

## Workflow

```bash
sudo synapsectl init          # asks a few questions, writes synapse.toml, creates secrets, renders
sudo synapsectl doctor        # checks the machine and the files
# then, with the rendered compose file (to become synapsectl apply):
docker compose -f /etc/synapse/rendered/compose.yml up -d --wait db
docker compose -f /etc/synapse/rendered/compose.yml run --rm bootstrap
docker compose -f /etc/synapse/rendered/compose.yml run --rm migrate
docker compose -f /etc/synapse/rendered/compose.yml run --rm --no-deps api \
    tenant create --slug <slug> --name "<organization>" --id <instance.tenant_id>
docker compose -f /etc/synapse/rendered/compose.yml run --rm --no-deps api \
    user create --email <admin email> --name "<name>" --role admin
docker compose -f /etc/synapse/rendered/compose.yml up -d --wait
```

`synapsectl init --from answers.toml` skips the questions, for scripted or repeated installs.

## synapse.toml

| Section | Keys | Notes |
|---|---|---|
| (top level) | `hardware` | `cpu-16`, `cpu-32` or `gpu`; sets memory limits (and later the models). The wizard suggests one from the installed RAM |
| `[instance]` | `id`, `tenant_id`, `organization`, `slug`, `hostname`, `locale` | IDs are generated once. `tenant_id` is the ID the tenant is created with, so rendering never depends on database state. `hostname` with the HTTPS port becomes `SYNAPSE_PUBLIC_URL`, which passkeys are bound to: **changing it later invalidates every registered passkey** |
| `[tls]` | `mode`, `email`, `certificate`, `private_key` | `internal` (Caddy's own CA; give its root certificate to the IT team), `provided` (the customer's PKI; files are copied into the secrets), `acme` (public hostnames only) |
| `[network]` | `http_port`, `https_port`, `subnet` | Change the ports only if 80/443 are taken; change the subnet only if it collides with the site's network |
| `[paths]` | `secrets_dir`, `render_dir` | Default `/etc/synapse/secrets` and `/etc/synapse/rendered` |
| `[images]` | `version` | The release to run |
| `[modules]` | `enabled` | Optional modules; see below |

Unknown keys, unknown modules and incomplete TLS settings are rejected, so a typo never falls back to a default silently.

## Modules

The wizard lists every module in [docs/product/modules.md](product/modules.md): reports, specifications, translation and calendar, each marked "coming soon" until it is built. A module that is not available cannot be enabled. When modules exist, enabling one also requires the licence ([ADR 0012](adr/0012-installer-modules-licensing.md)).

## Secrets

`init` creates every secret with a cryptographic random generator: database role passwords, the superuser connection for bootstrap, the CSRF key, the TOTP encryption key and the audit signing key. Existing files are never overwritten, so running `init` again on the same secrets directory is harmless.

Files are mode 0400 in a 0700 directory. When run as root, each file is also handed to the container user that reads it (uid 999 for the database, 10001 for the application and web front), because Compose mounts secret files with their host ownership.

## Rendered files

| File | Contents |
|---|---|
| `compose.yml` | The services from [deployment.md](deployment.md), with the tenant, the tier's memory limits, the ports and the secret paths filled in |
| `caddy/tls.caddy` | The TLS directive, mounted into the web front |
| `manifest.json` | SHA-256 of each file and of the configuration |

Each file starts with a "generated, do not edit" header. The site configuration itself stays in the image ([deploy/web/Caddyfile](../deploy/web/Caddyfile)); rendering only sets its address and TLS, so there is one copy of it.

Two details that matter for non-standard ports:

- The web front listens on the same port numbers inside and outside the container, and an unprivileged-port sysctl lets it bind 80 and 443 without any capability.
- When `https_port` is not 443, the port is written into the site address. Caddy omits a port equal to its own `https_port` setting from HTTP-to-HTTPS redirects, which would send users to the wrong port.

## doctor

| Check | FAIL when | WARN when |
|---|---|---|
| docker | No engine or no Compose plugin | |
| cpu | x86 without AVX2 (local models need it) | CPU flags unreadable |
| memory | Less than the tier needs (16 or 32 GiB, with 10% tolerance) | |
| disk | | Less than 50 GiB free |
| port (http, https) | In use by another program | |
| secrets | A file is missing, empty, readable by others or (as root) owned by the wrong user | |
| rendered files | Not rendered, edited by hand, or different from what the current configuration and synapsectl version produce | |

`doctor --running` accepts the ports being in use, for checks on a running installation. The exit code is 1 if any check fails.

## Not done yet

- `apply`: running the steps in the workflow above, idempotently.
- `backup`, `restore`, `upgrade`, `support-bundle`, the offline bundle, licence files.
- A web-based setup screen for the same steps, served on localhost during installation.
