# Installer: synapsectl

Status: init, render, doctor and apply, 2026-09-28; backup, restore, upgrade and support-bundle, 2026-10-06. Decision records: [ADR 0012](adr/0012-installer-modules-licensing.md), [ADR 0021](adr/0021-backups.md) (backups). Code: [synapsectl/](../synapsectl/).

`synapsectl` runs on the customer's machine, operated by the vendor's installer. One file, `/etc/synapse/synapse.toml`, describes the installation; everything else is produced from it.

## Workflow

```bash
sudo synapsectl init          # asks a few questions, writes synapse.toml, creates secrets, renders
sudo synapsectl bundle load /media/usb/synapse-1.0.0  # without the internet: images, models
sudo synapsectl models fetch  # with it: the model files
sudo synapsectl doctor        # checks the machine and the files
sudo synapsectl apply --admin-email admin@example.org --admin-name "Admin"
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
| `[models]` | `dir`, `accelerator`, `gpu_groups` | Where the model files are (default `/var/lib/synapse/models`); `cpu` or `vulkan` (a GPU, integrated ones included); for `vulkan`, the host groups that own `/dev/dri`'s devices. The wizard proposes `vulkan` with those groups when it finds a GPU |
| `[modules]` | `enabled` | Optional modules; see below |
| `[backup]` | `repository`, `staging_dir`, `time`, `keep_daily`, `keep_weekly`, `keep_monthly` | Where restic keeps the snapshots (an absolute path: a mounted NAS share or disk; unset, no backups are taken), where the dump waits on its way there (default `/var/lib/synapse/backup`), when the nightly backup runs (default 02:30) and how many snapshots are kept (7, 4, 6). See [Backups](#backups) |

Unknown keys, unknown modules and incomplete TLS settings are rejected, so a typo never falls back to a default silently.

## apply

`apply` brings the machine to the state `synapse.toml` describes. Every step is safe to repeat, so the same command installs, repairs, and (after `[images] version` is changed) upgrades; `upgrade` below does that with a backup first:

1. Renders the files again and runs the doctor checks. Any FAIL stops here, before anything starts. If the services are already running, their ports count as in use by Synapse.
2. Starts the database, then runs bootstrap (creates or repairs roles and schema) and the migrations.
3. Creates the tenant with the ID from `synapse.toml` (`synapse tenant create --if-missing`; an existing tenant with another slug is an error).
4. Creates the first administrator only if the tenant has no active one. The first run therefore needs `--admin-email` and `--admin-name`; later runs do not. The password is prompted in the terminal, or read from `--admin-password-file` for scripted installs (the file is mounted read-only into the one container that reads it, so it must be readable by uid 10001).
5. Starts every service, waits until each is healthy, and runs the checks again.
6. With `[backup] repository` set, installs the systemd timers of the nightly backup and the quarterly verification (as root on a systemd machine; otherwise it prints the commands to schedule).

A failed step stops `apply` with the step's name and its output; running it again continues from wherever the installation is. Tested by [tests/test_apply.py](../synapsectl/tests/test_apply.py) with a scripted Docker, and by hand on a fresh install: install, then a second run with nothing to do.

## Modules

The wizard lists every module in [docs/product/modules.md](product/modules.md): reports, specifications, translation and calendar, each marked "coming soon" until it is built. A module that is not available cannot be enabled. When modules exist, enabling one also requires the licence ([ADR 0012](adr/0012-installer-modules-licensing.md)).

## Models

The model servers ([deployment.md](deployment.md#model-servers), [ADR 0018](adr/0018-model-defaults.md)) read GGUF files from `models.dir`. Which files depends on `models.accelerator`: on a GPU the encoders run with 8-bit weights, on the CPU with 16-bit ones; the chat model is the same file for both. [models.py](../synapsectl/src/synapsectl/models.py) pins each by SHA-256 and size.

- `synapsectl models fetch [--dir D] [--accelerator cpu|vulkan]` gets what is missing: the chat model (Qwen3.5-4B Q4_K_M) is downloaded from its pinned Hugging Face revision; the encoders (bge-m3, bge-reranker-v2-m3) are converted from their pinned revisions with llama.cpp's own converter at the servers' build, in a throwaway container with the converter's dependencies pinned, running as the calling user. The conversion is deterministic: a fresh container produced the measured file byte for byte (3.5 minutes for bge-m3 on the reference machine), so the SHA-256 also proves the file is the one the benchmarks measured. A file whose digest is wrong is removed.
- `synapsectl models check [--verify]` reports missing files and wrong sizes; with `--verify` it also reads every file for its SHA-256 (4 to 5 GB).
- Offline installs get the files in the bundle and only check them.

## upgrade

`synapsectl upgrade --to VERSION` moves the installation to another release:

1. The release's images must be on the machine (`synapsectl bundle load`, below). A release on another PostgreSQL major version is refused: its server would not start on this data directory.
2. A backup is taken with the running release. Migrations only go forward, so restoring this backup with the old release is the way back; without backups set up, the upgrade is refused.
3. `[images] version` is changed in `synapse.toml`, and only that line: comments and hand edits stay.
4. `apply` renders the files, checks the machine, migrates the database and starts the release.

If `apply` stops, the new version stays written, so `apply` can run again once the cause is fixed; the error also lists the commands that go back to the old release with the backup just taken. Tested by [tests/test_upgrade.py](../synapsectl/tests/test_upgrade.py) with a scripted Docker.

## bundle

A release in one directory, for machines without the internet ([bundle.py](../synapsectl/src/synapsectl/bundle.py)):

```
synapse-VERSION/
  manifest.json   the version, and every file: what it is, its SHA-256 and size
  SHA256SUMS      the same hashes, as sha256sum -c reads them
  images/         the release's three images, the llama.cpp servers' (CPU and Vulkan) and restic's
  models/         the model files of both accelerators
```

- `synapsectl bundle create DIR --release VERSION [--models-from DIR]` makes one (on the vendor's machine): the release's images must be there, the others are pulled by their pinned digests, and every model file must have its SHA-256 (`models fetch` gets them). About 10 GB. Nothing is left half made: the bundle is written as `synapse-VERSION.partial` and renamed when complete.
- `synapsectl bundle verify DIR` checks every file listed, its size and SHA-256, that nothing else is there, and that `SHA256SUMS` says the same; it needs no `synapse.toml`.
- `sudo synapsectl bundle load DIR` verifies, then loads the images into Docker and copies the model files the installation's accelerator needs into `models.dir` (files already there and right are kept). A damaged bundle loads nothing. It then says what to run: `apply` on a new machine, `upgrade --to VERSION` on one running another release.

The hashes find a bundle damaged on its way (a copy cut short, a failing disk), not one changed on purpose: that needs the vendor's signature over the manifest (ADR 0012), which comes with the vendor's signing key. Tested by [tests/test_bundle.py](../synapsectl/tests/test_bundle.py) with a scripted Docker.

## support-bundle

`sudo synapsectl support-bundle [--output FILE]` writes what the vendor's support needs into one `.tar.gz` (mode 0600, owned by the user who ran `sudo`), by default `synapse-support-SLUG-TIME.tar.gz` in the current directory. Nothing is sent: the operator reads it, every file in it being text, and passes it on.

| File | Contents |
|---|---|
| `versions.txt`, `docker-version.txt` | synapsectl, the image version, the operating system, Docker |
| `doctor.txt` | Every check, as `synapsectl doctor` prints it |
| `synapse.toml`, `rendered/` | The configuration and the rendered `compose.yml` and `manifest.json` |
| `secrets.txt` | Each secret's name, mode, owner and size; never a value |
| `services.json`, `logs/SERVICE.log` | Every service's state and its last 2000 log lines |
| `backup-status.json`, `disk.txt`, `docker-df.txt` | The last backups and verifications, free space where Synapse keeps data, Docker's disk use |

Logs leave the organisation, so everything is redacted before it is written ([support.py](../synapsectl/src/synapsectl/support.py)): the values of every secret (the bundle is refused when one cannot be read, so it runs as root), email addresses, IP addresses outside the stack's own subnet (each replaced by a pseudonym that is the same throughout one bundle, so a user's requests can still be followed, and that cannot be reversed: its salt is never stored), query string values (uploads carry file names there), cookie, authorization and CSRF header values, passwords in connection strings, and the values PostgreSQL quotes in its errors. Document contents are never logged. Tested by [tests/test_support.py](../synapsectl/tests/test_support.py), and on the last 3000 lines of each service of the evaluation stack: no client address or CSRF token was left.

## Backups

```bash
sudo synapsectl backup init     # the backup password, the backup containers, the repository
sudo synapsectl backup          # a backup now (the timer runs one every night)
sudo synapsectl backup list
sudo synapsectl backup verify   # restore the latest dump into a scratch database and count it
sudo synapsectl restore [--snapshot ID] [--replace]   # then: synapsectl apply
```

A backup is one encrypted restic snapshot of the database dump, the uploaded files, `synapse.toml` and the secrets, with a manifest of every table's rows. A restore checks the dump, the rows and the image version, and replaces the database and the files; on a new machine `restore --configuration-from REPOSITORY --password-file FILE` first brings back `synapse.toml` and the secrets. How it works, what is checked and the steps on a new machine: [design/backup.md](design/backup.md).

## Secrets

`init` creates every secret with a cryptographic random generator: database role passwords, the superuser connection for bootstrap, the CSRF key, the TOTP encryption key, the audit signing key, one API key per model server (`embed_key`, `rerank_key`, `chat_key`), read by the server and by the processes that call it, and with backups set up the key of the backup repository (`backup_password`; `backup init` creates it on an installation that had no backups). Existing files are never overwritten, so running `init` again on the same secrets directory is harmless.

Files are mode 0400 in a 0700 directory. When run as root, each file is also handed to the container user that reads it (uid 999 for the database, 10001 for the application and web front), because Compose mounts secret files with their host ownership.

## Rendered files

| File | Contents |
|---|---|
| `compose.yml` | The services from [deployment.md](deployment.md), with the tenant, the tier's memory limits, the ports, the secret paths and the model servers for the accelerator filled in |
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
| clock | | NTP does not keep the host's clock, or `timedatectl` cannot tell (the audit log, logs and backups carry its time) |
| port (http, https) | In use by another program | |
| secrets | A file is missing, empty, readable by others or (as root) owned by the wrong user | |
| rendered files | Not rendered, edited by hand, or different from what the current configuration and synapsectl version produce | |
| models | A model file the accelerator needs is missing or has the wrong size (`synapsectl models check --verify` compares digests) | |
| gpu | `vulkan` without a GPU, `models.gpu_groups` missing a group that owns `/dev/dri`'s devices, or the Vulkan server image, run as the servers run, not seeing the GPU | A GPU is present but the models run on the CPU (the detail gives the settings to change) |
| backup | | Backups are not set up, the repository is missing (disk not mounted?), the last backup failed, or the last good one is more than 2 days old |

`doctor --running` accepts the ports being in use, for checks on a running installation. The exit code is 1 if any check fails.

## Not done yet

- The bundle's signature (the vendor's key) and a release manifest `upgrade` checks (image digests, migration heads); licence files.
- Upgrades across PostgreSQL major versions (through a backup and a restore).
- Backups to S3-compatible storage (a NAS share or disk mounted on the host until then), and the backup status on the Operations page.
- A web-based setup screen for the same steps, served on localhost during installation.
