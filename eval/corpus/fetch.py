"""Download the evaluation corpus listed in manifest.csv into eval/corpus/files/.

The files are not committed: several are published for reading, not redistribution (see the
licence notes in README.md). Each download is checked against the manifest's expected size and
recorded with its SHA-256 in files/checksums.csv, so later runs detect changed documents.

Usage (from the repository root):

    python3 eval/corpus/fetch.py            # download missing files
    python3 eval/corpus/fetch.py --verify   # only verify files already downloaded
"""

import argparse
import csv
import hashlib
import ssl
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "manifest.csv"
FILES = HERE / "files"
CHECKSUMS = FILES / "checksums.csv"
# Some government servers send their certificate without the intermediate that links it to a
# trusted root. Browsers fetch it themselves; Python does not. These are the public
# intermediates those servers are missing (see intermediates/README.md). Verification stays on:
# an intermediate only helps if it chains to a root the system already trusts.
INTERMEDIATES = HERE / "intermediates"

EXTENSIONS = {"PDF": ".pdf", "DOCX": ".docx", "DOC": ".doc", "XLSX": ".xlsx", "PPTX": ".pptx"}
USER_AGENT = "Mozilla/5.0 (compatible; corpus-fetch/1.0; evaluation research)"
TIMEOUT_SECONDS = 120
# Pause between downloads so small public sites are not hammered.
PAUSE_SECONDS = 1.0


def target_path(row: dict[str, str]) -> Path:
    return FILES / f"{row['id']}{EXTENSIONS[row['format']]}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tls_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    for certificate in sorted(INTERMEDIATES.glob("*.pem")):
        context.load_verify_locations(cafile=certificate)
    return context


TLS = tls_context()


def download(row: dict[str, str], path: Path) -> None:
    # URLs come from the reviewed manifest, not from user input.
    request = urllib.request.Request(row["source_url"], headers={"User-Agent": USER_AGENT})  # noqa: S310
    partial = path.with_suffix(path.suffix + ".part")
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS, context=TLS) as response:  # noqa: S310
        content_type = response.headers.get("Content-Type", "")
        if "text/html" in content_type:
            raise RuntimeError(f"server returned HTML instead of a file ({content_type})")
        with partial.open("wb") as handle:
            while block := response.read(1 << 20):
                handle.write(block)
    partial.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verify", action="store_true", help="verify only, download nothing")
    args = parser.parse_args()

    FILES.mkdir(exist_ok=True)
    with MANIFEST.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    results: list[tuple[str, str, int, str]] = []
    failures: list[str] = []
    for row in rows:
        path = target_path(row)
        if not path.exists():
            if args.verify:
                failures.append(f"{row['id']}: missing")
                continue
            try:
                download(row, path)
            except Exception as error:  # noqa: BLE001  (report every failure, keep going)
                failures.append(f"{row['id']}: {error}")
                continue
            time.sleep(PAUSE_SECONDS)
        size = path.stat().st_size
        expected = int(row["size_bytes"] or 0)
        if expected and size != expected:
            failures.append(f"{row['id']}: size {size} differs from manifest {expected}")
        results.append((row["id"], path.name, size, sha256(path)))

    with CHECKSUMS.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "file", "size_bytes", "sha256"])
        writer.writerows(results)

    for failure in failures:
        print(failure, file=sys.stderr)
    print(f"corpus: {len(results)} of {len(rows)} files present, {len(failures)} problems")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
