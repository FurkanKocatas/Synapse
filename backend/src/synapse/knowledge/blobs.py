"""File storage behind the ``BlobStore`` port (ADR 0003).

A blob is named by the SHA-256 of its bytes, under a directory per tenant. Writing is atomic:
the bytes go to a temporary file on the same file system first and are renamed into place, so a
reader never sees a half-written file and a crash leaves at most a stray temporary file.
"""

import hashlib
import os
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol
from uuid import UUID

READ_BLOCK = 1 << 20


@dataclass(frozen=True)
class Incoming:
    """A file received but not yet stored: where it is, its size and its SHA-256."""

    path: Path
    size_bytes: int
    sha256: bytes


class TooLargeError(ValueError):
    def __init__(self, limit_bytes: int) -> None:
        super().__init__(f"larger than {limit_bytes} bytes")
        self.limit_bytes = limit_bytes


class BlobStore(Protocol):
    def incoming_dir(self) -> Path: ...

    def put(self, tenant_id: UUID, incoming: Incoming) -> None:
        """Move an incoming file into the store; keeps the existing copy if there is one."""
        ...

    def open(self, tenant_id: UUID, sha256: bytes) -> BinaryIO: ...

    def delete(self, tenant_id: UUID, sha256: bytes) -> None: ...


class LocalBlobStore:
    """Blobs on a local directory, such as a Docker volume."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def incoming_dir(self) -> Path:
        # Inside the store, so moving a finished upload into place is a rename.
        path = self._root / ".incoming"
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        return path

    def path(self, tenant_id: UUID, sha256: bytes) -> Path:
        name = sha256.hex()
        return self._root / str(tenant_id) / name[:2] / name[2:4] / name

    def put(self, tenant_id: UUID, incoming: Incoming) -> None:
        target = self.path(tenant_id, incoming.sha256)
        if target.exists():
            incoming.path.unlink(missing_ok=True)
            return
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with incoming.path.open("rb") as handle:
            os.fsync(handle.fileno())
        incoming.path.replace(target)

    def open(self, tenant_id: UUID, sha256: bytes) -> BinaryIO:
        return self.path(tenant_id, sha256).open("rb")

    def delete(self, tenant_id: UUID, sha256: bytes) -> None:
        self.path(tenant_id, sha256).unlink(missing_ok=True)


class Receiver:
    """Writes an upload to a temporary file while hashing and counting it.

    The size limit is enforced while receiving, so an oversized upload never fills the disk.
    """

    def __init__(self, directory: Path, *, limit_bytes: int) -> None:
        self._path = directory / f"{secrets.token_hex(16)}.part"
        self._handle = self._path.open("xb")
        self._digest = hashlib.sha256()
        self._size = 0
        self._limit = limit_bytes

    def write(self, block: bytes) -> None:
        self._size += len(block)
        if self._size > self._limit:
            self.discard()
            raise TooLargeError(self._limit)
        self._digest.update(block)
        self._handle.write(block)

    def finish(self) -> Incoming:
        self._handle.close()
        return Incoming(path=self._path, size_bytes=self._size, sha256=self._digest.digest())

    def discard(self) -> None:
        self._handle.close()
        self._path.unlink(missing_ok=True)


def copy_to(store: BlobStore, tenant_id: UUID, sha256: bytes, destination: BinaryIO) -> None:
    with store.open(tenant_id, sha256) as source:
        shutil.copyfileobj(source, destination, READ_BLOCK)
