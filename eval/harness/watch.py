"""Measures every new commit on main on the reference machine, and reports to GitHub.

    flock -n ~/synapse-ci/lock python3 ~/synapse-ci/repo/eval/harness/watch.py

Run by cron every 15 minutes (README.md). It needs nothing from GitHub but what it reads:
only commits on ``origin/main`` are measured, never a fork's or a pull request's, so no code
from outside runs on this machine. Each run:

1. Starts only between 08:00 and 21:30 (the machine is quiet at night; a run with a fresh
   ingestion takes about two hours) and stops whatever runs at 00:05.
2. Fetches ``origin/main`` into its own clone (``~/synapse-ci/repo``, never the development
   checkout) and takes the newest commit not measured yet; commits that change only
   documentation are marked and skipped.
3. Brings the ``synapse-golden`` stack to that commit: images built, services up with the
   models on the integrated GPU, migrations applied, ``synapse knowledge reindex``. The corpus
   is ingested again from scratch (an hour) only when the code or the model that ingestion
   depends on changed (``INGESTION``); otherwise the stack keeps its documents.
4. Runs run.py against it with the baseline at that commit, and posts the result as the
   commit status ``synapse/eval`` with a comment holding the report.

State in ``~/synapse-ci/state``: the last commit measured, the ingestion's fingerprint, every
run's report under ``runs/<commit>/``. The clone's ``.dev`` and ``eval/corpus/files`` link to
the development checkout's (secrets, the stack's tenant, the model files, the corpus).
"""

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
CI = HOME / "synapse-ci"
REPO = CI / "repo"
STATE = CI / "state"
DEV = HOME / "Documents" / "dev" / "Synapse"
CONTEXT = "synapse/eval"
START_FROM, START_UNTIL, STOP_AT = dt.time(8, 0), dt.time(21, 30), dt.time(0, 5)
MAX_ATTEMPTS = 2
BUILD_ATTEMPTS = 3
BASE = "http://127.0.0.1:8490"
EMAIL = "editor@golden.example"
# What a chunk's text, terms and vector depend on: a change here means ingesting again.
INGESTION = [
    "backend/src/synapse/knowledge/chunking.py",
    "backend/src/synapse/knowledge/dedup.py",
    "backend/src/synapse/knowledge/entities.py",
    "backend/src/synapse/knowledge/filetypes.py",
    "backend/src/synapse/knowledge/headings.py",
    "backend/src/synapse/knowledge/language.py",
    "backend/src/synapse/knowledge/ocr.py",
    "backend/src/synapse/knowledge/parsing.py",
    "backend/src/synapse/knowledge/processing.py",
    "backend/src/synapse/knowledge/quality.py",
    "backend/src/synapse/knowledge/rapid.py",
    "backend/src/synapse/knowledge/search.py",
    "backend/src/synapse/knowledge/structure.py",
    "backend/src/synapse/knowledge/turkish.py",
    "backend/src/synapse/knowledge/data",
    "backend/src/synapse/models/llama.py",
    "eval/corpus/manifest.csv",
    "synapsectl/src/synapsectl/models.py",
]
DOCS_ONLY = ("docs/", "README.md")


def log(message: str) -> None:
    print(f"{dt.datetime.now().astimezone():%Y-%m-%d %H:%M:%S} {message}", flush=True)


def run(
    *command: str, cwd: Path = REPO, timeout: float | None = None, env: dict[str, str] | None = None
) -> str:
    result = subprocess.run(  # noqa: S603
        command, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env, check=False
    )
    if result.returncode != 0:
        tail = (result.stdout + result.stderr)[-2000:]
        raise RuntimeError(f"{' '.join(command[:4])} exited {result.returncode}: {tail}")
    return result.stdout


def seconds_left(now: dt.datetime) -> float:
    stop = dt.datetime.combine(now.date() + dt.timedelta(days=1), STOP_AT, tzinfo=now.tzinfo)
    return (stop - now).total_seconds()


def github_repo() -> str:
    return run("gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner").strip()


def status(repo: str, sha: str, state: str, description: str) -> None:
    run(
        "gh",
        "api",
        "-X",
        "POST",
        f"repos/{repo}/statuses/{sha}",
        "-f",
        f"state={state}",
        "-f",
        f"context={CONTEXT}",
        "-f",
        f"description={description[:139]}",
    )


def comment(repo: str, sha: str, body: Path) -> None:
    run("gh", "api", "-X", "POST", f"repos/{repo}/commits/{sha}/comments", "-F", f"body=@{body}")


def fingerprint() -> str:
    """The ingestion's files as git tracks them at the checked-out commit: ``__pycache__`` and
    anything else untracked in those directories does not count."""
    lines = []
    for name in INGESTION:
        try:
            lines.append(f"{name} {run('git', 'rev-parse', f'HEAD:{name}').strip()}")
        except RuntimeError:
            lines.append(f"{name} missing")
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def stack_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = f"{HOME / '.local' / 'bin'}:{env.get('PATH', '')}"
    env.update(
        SYNAPSE_STACK_PORT="8490",
        SYNAPSE_STACK_SUBNET="172.29.210.0/24",
        SYNAPSE_STACK_ENV="golden.env",
        SYNAPSE_STACK_MODELS="1",
        SYNAPSE_MODELS_DIR=str((DEV / ".dev" / "models").resolve()),
        SYNAPSE_RENDER_GID=str(Path("/dev/dri/renderD128").stat().st_gid),
        SYNAPSE_VIDEO_GID=str(Path("/dev/dri/card0").stat().st_gid),
    )
    return env


def stack(*arguments: str, timeout: float = 1800) -> str:
    files = ["-f", "deploy/compose.stack.yml", "-f", "deploy/compose.vulkan.yml"]
    command = ["docker", "compose", "-p", "synapse-golden", *files, "--profile", "models"]
    return run(*command, *arguments, timeout=timeout, env=stack_env())


def link(target: Path, name: Path) -> None:
    if not name.is_symlink():
        name.parent.mkdir(parents=True, exist_ok=True)
        name.symlink_to(target)


def prepare(sha: str) -> None:
    run("git", "checkout", "-q", "--detach", sha)
    link(DEV / ".dev", REPO / ".dev")
    link(DEV / "eval" / "corpus" / "files", REPO / "eval" / "corpus" / "files")
    documents = REPO / "eval" / "retrieval" / "work" / "product" / "documents.json"
    if not documents.exists():
        documents.parent.mkdir(parents=True, exist_ok=True)
        documents.write_bytes((DEV / "eval/retrieval/work/product/documents.json").read_bytes())


def upgrade(timeout: float) -> bool:
    """The stack at the checked-out commit; True when the corpus had to be ingested again."""
    for attempt in range(BUILD_ATTEMPTS):
        try:
            stack("build", "--quiet")
            break
        except RuntimeError:  # pragma: no cover  (a registry or download hiccup)
            if attempt == BUILD_ATTEMPTS - 1:
                raise
            time.sleep(30)
    current = fingerprint()
    stored = STATE / "ingestion-tree"
    fresh = stored.exists() and stored.read_text() != current
    uv = ["uv", "run", "--directory", "backend", "python", "../eval/retrieval/product.py"]
    access = [
        "--base",
        BASE,
        "--email",
        EMAIL,
        "--password-file",
        str(DEV / ".dev/golden-password"),
    ]
    if fresh:
        log("ingestion changed: the corpus is ingested again")
        stack("down", "-v")
        (DEV / ".dev" / "golden.env").unlink(missing_ok=True)
        stack("up", "-d", "--wait", "db")
        stack("run", "--rm", "bootstrap")
        stack("run", "--rm", "migrate")
        tenant = stack(
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "api",
            "tenant",
            "create",
            "--slug",
            "golden",
            "--name",
            "Golden",
        )
        (DEV / ".dev" / "golden.env").write_text(
            f"SYNAPSE_TENANT_ID={tenant.strip().splitlines()[-1]}\n"
        )
        stack(
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "-v",
            f"{DEV / '.dev/golden-password'}:/run/password:ro",
            "api",
            "user",
            "create",
            "--email",
            EMAIL,
            "--name",
            "Golden Editor",
            "--role",
            "editor",
            "--password-file",
            "/run/password",
        )
    stack("up", "-d", "--wait")
    if fresh:
        run(*uv, "upload", *access, timeout=timeout, env=stack_env())
    else:
        log(stack("run", "--rm", "--no-deps", "-T", "worker", "knowledge", "reindex").strip())
    stored.write_text(current)
    return fresh


def measure(repo: str, sha: str, deadline: float) -> None:
    out = STATE / "runs" / sha
    status(repo, sha, "pending", "measuring the golden set on the reference machine")
    started = time.monotonic()
    fresh = upgrade(deadline - time.monotonic())
    command = [
        "uv",
        "run",
        "--directory",
        "backend",
        "python",
        "../eval/harness/run.py",
        "--base",
        BASE,
        "--email",
        EMAIL,
        "--password-file",
        str(DEV / ".dev/golden-password"),
        "--documents",
        str(REPO / "eval/retrieval/work/product/documents.json"),
        "--out",
        str(out),
        "--commit",
        sha,
        "--wait-ready",
        *(["--fresh-ingestion"] if fresh else []),
    ]
    baseline = REPO / "eval" / "harness" / "baseline.json"
    if baseline.exists():
        command += ["--baseline", str(baseline)]
    result = subprocess.run(  # noqa: S603
        command,
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=max(60.0, deadline - time.monotonic()),
        env=stack_env(),
        check=False,
    )
    (out / "run.log").parent.mkdir(parents=True, exist_ok=True)
    (out / "run.log").write_text(result.stdout + result.stderr)
    report_file = out / "report.json"
    if not report_file.exists():
        raise RuntimeError(f"run.py wrote no report: {(result.stdout + result.stderr)[-1500:]}")
    report = json.loads(report_file.read_text())
    minutes = round((time.monotonic() - started) / 60)
    verdict = report["verdict"]
    failed = [g["path"] for g in report["gates"] if not g["ok"]]
    a = report["answers"]
    summary = (
        f"correct {a['correct']}, unanswerable refused {a['unanswerable_refused_count']}/"
        f"{a['unanswerable']}, hit@10 {report['retrieval']['as_written']['all']['hit@10']}"
        + (f"; failed: {', '.join(failed)}" if failed else "")
        + (", corpus ingested again" if fresh else "")
        + f" ({minutes} min)"
    )
    comment(repo, sha, out / "report.md")
    status(repo, sha, "failure" if verdict == "fail" else "success", summary)
    log(f"{sha[:7]} {verdict}: {summary}")


def main() -> int:
    # cron's PATH lacks ~/.local/bin, where gh and uv are.
    os.environ["PATH"] = f"{HOME / '.local' / 'bin'}:{os.environ.get('PATH', '/usr/bin:/bin')}"
    now = dt.datetime.now().astimezone()
    if not START_FROM <= now.time() < START_UNTIL:
        return 0
    STATE.mkdir(parents=True, exist_ok=True)
    run("git", "fetch", "-q", "origin", "main")
    sha = run("git", "rev-parse", "origin/main").strip()
    last_file, attempts_file = STATE / "last", STATE / "attempts"
    last = last_file.read_text().strip() if last_file.exists() else ""
    if sha == last:
        return 0
    repo = github_repo()
    if last:
        changed = run("git", "diff", "--name-only", last, sha).split()
        if changed and all(name.startswith(DOCS_ONLY) or name.endswith(".md") for name in changed):
            status(repo, sha, "success", f"documentation only since {last[:7]}: not measured")
            last_file.write_text(sha)
            log(f"{sha[:7]} documentation only")
            return 0
    attempts = json.loads(attempts_file.read_text()) if attempts_file.exists() else {}
    if attempts.get(sha, 0) >= MAX_ATTEMPTS:
        return 0
    attempts[sha] = attempts.get(sha, 0) + 1
    attempts_file.write_text(json.dumps(attempts))
    log(f"{sha[:7]} measuring (attempt {attempts[sha]})")
    deadline = time.monotonic() + seconds_left(now)
    try:
        prepare(sha)
        measure(repo, sha, deadline)
    except (RuntimeError, subprocess.TimeoutExpired, OSError) as error:
        log(f"{sha[:7]} error: {error}")
        final = attempts[sha] >= MAX_ATTEMPTS
        status(repo, sha, "error" if final else "pending", f"not measured: {str(error)[:100]}")
        if final:
            last_file.write_text(sha)
        return 1
    last_file.write_text(sha)
    return 0


if __name__ == "__main__":
    sys.exit(main())
