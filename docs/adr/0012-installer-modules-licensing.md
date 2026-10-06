# 0012. Installer, module registry and offline licensing

- Status: accepted (backups: refined by [ADR 0021](0021-backups.md))
- Date: 2026-09-28

## Context

The vendor's installer sets up each customer box and chooses which optional modules are enabled. Customers include air-gapped public institutions. Hand-edited configuration on each server drifts between environments, and containers that hold the Docker socket are root on the host.

Research: [04-architecture.md, section 6](../research/04-architecture.md).

## Decision

**`synapsectl`**, a vendor-operated command line tool with an interactive wizard.

- Single source of truth: `/etc/synapse/synapse.toml` (instance id, hostname, TLS mode, hardware tier, enabled modules, models, backup target, locale). Compose file, Caddyfile, database settings and model server flags are **rendered** from it and carry a "generated, do not edit" header.
- Commands: `init` (wizard: hardware detection, tier, TLS, first admin, modules), `apply` (idempotent: render, load images, create secrets, migrate, start), `doctor` (CPU flags, RAM, disk, ports, clock, certificate expiry, rendered files vs `synapse.toml`, image digests vs release manifest), `backup`, `restore`, `upgrade`, `support-bundle` (redacted).
- The wizard is a terminal UI for the vendor's installer. A web-based setup screen for the same steps is planned after v1, served only on localhost during installation.
- No container ever mounts the Docker socket.

**Module registry.** Each optional module is a Python package under `synapse.modules.<name>` with a manifest:

| Field | Meaning |
|---|---|
| `name`, `version` | Identity |
| `requires` | Core version range and other modules |
| `license_feature` | Feature flag that must be present in the licence |
| `migrations` | Its own Alembic branch |
| `permissions` | Permissions it adds to the role model |
| `ui_routes` | Routes the SPA may lazy-load |
| `jobs` | Job types and queues it uses |
| `compose_profile` | Extra containers, if any |

A module is active only if it is enabled in `synapse.toml`, present in the verified licence, and its migrations are at head. Disabling a module hides its routes and stops its jobs but never drops its tables. SaaS uses the same registry with per-tenant enablement.

**Licence.** A JSON payload (`license_id`, `customer`, `instance_id`, `edition`, `modules`, `max_users`, `issued_at`, `not_after`, `grace_days`) signed with Ed25519. The vendor's signing key stays offline; the public key is built into the image. The licence is bound to the `instance_id` generated at install.

- Invalid signature: licensed modules do not start (fail closed).
- Expiry: grace period with banners, then licensed modules become read-only. **Core document access and export always remain available**; customer data is never held hostage.

**Upgrades.** A signed release manifest pins image digests and migration heads. `upgrade` runs `doctor`, takes a mandatory backup, loads images, runs migrations with the migrator role, then starts the new version. The API refuses to start on a schema mismatch. Migrations follow expand and contract.

**Backups.** Nightly `pg_dump -Fc` plus blobs plus `synapse.toml` and encrypted secrets, packed and encrypted with restic to a customer target (NAS, USB, S3-compatible). Retention 7 daily, 4 weekly, 6 monthly. A restore drill into a scratch database runs quarterly and reports on the Operations page.

**Air-gapped installs.** An offline bundle with all images, model files, `synapsectl`, the release manifest, checksums, signatures and SBOMs, verified before loading. No telemetry and no update checks unless enabled.

## Consequences

- Configuration drift becomes detectable (`doctor`) instead of silent.
- Licensing is deterrence, not DRM; that is acceptable and matches public-sector expectations.

## Alternatives considered

- **Nextcloud AIO style master container with the Docker socket:** root on the host from a web-facing container.
- **Hand-edited `.env` files:** the drift problem we are avoiding.
- **Online licence activation:** impossible for air-gapped customers.
