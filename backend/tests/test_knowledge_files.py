"""File type detection, the blob store and receiving uploads."""

import hashlib
import io
import os
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from synapse.knowledge.blobs import LocalBlobStore, Receiver, TooLargeError
from synapse.knowledge.documents import clean_filename, default_title, named_for
from synapse.knowledge.filetypes import MediaType, UnsupportedFileError, detect

WORD_MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
MACRO_WORD = "application/vnd.ms-word.document.macroEnabled.main+xml"


def office_package(main_type: str | None, *, content_types: bytes | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        if content_types is None and main_type is not None:
            content_types = (
                '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                'package/2006/content-types"><Default Extension="xml" '
                f'ContentType="application/xml"/><Override PartName="/main.xml" '
                f'ContentType="{main_type}"/></Types>'
            ).encode()
        if content_types is not None:
            package.writestr("[Content_Types].xml", content_types)
        package.writestr("main.xml", "<x/>")
    return buffer.getvalue()


def written(tmp_path: Path, data: bytes, name: str = "sample.bin") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"%PDF-1.7\n%\xe2\xe3\n1 0 obj", MediaType.PDF),
        (b"\x00\x00junk before the header %PDF-1.4\n", MediaType.PDF),
        (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", MediaType.PNG),
        (b"\xff\xd8\xff\xe0\x00\x10JFIF", MediaType.JPEG),
        (b"II*\x00\x08\x00\x00\x00", MediaType.TIFF),
        (b"MM\x00*\x00\x00\x00\x08", MediaType.TIFF),
        (office_package(WORD_MAIN), MediaType.DOCX),
        (
            office_package(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
            ),
            MediaType.XLSX,
        ),
        (
            office_package(
                "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
            ),
            MediaType.PPTX,
        ),
    ],
)
def test_types_come_from_the_bytes(tmp_path: Path, data: bytes, expected: MediaType) -> None:
    # The name says nothing: every sample is called sample.bin.
    assert detect(written(tmp_path, data)) is expected


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"Just some text pretending to be a PDF", "unknown_type"),
        (bytes.fromhex("d0cf11e0a1b11ae1") + b"\x00" * 64, "legacy_office"),
        (office_package(MACRO_WORD), "unknown_type"),
        (office_package(None), "unknown_type"),  # a plain zip, no content types
        (b"PK\x03\x04 not really a zip", "unknown_type"),
        (
            office_package(
                None,
                content_types=(
                    b'<?xml version="1.0"?><!DOCTYPE t [<!ENTITY a "aaaaaaaaaa">'
                    b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><Types>&b;</Types>'
                ),
            ),
            "unknown_type",
        ),
    ],
)
def test_other_content_is_refused_with_a_reason(tmp_path: Path, data: bytes, reason: str) -> None:
    with pytest.raises(UnsupportedFileError) as refused:
        detect(written(tmp_path, data, "report.pdf"))
    assert refused.value.reason == reason


def test_receiving_hashes_counts_and_enforces_the_limit(tmp_path: Path) -> None:
    receiver = Receiver(tmp_path, limit_bytes=10)
    receiver.write(b"hello ")
    receiver.write(b"doc")
    incoming = receiver.finish()
    assert incoming.size_bytes == 9
    assert incoming.sha256 == hashlib.sha256(b"hello doc").digest()
    assert incoming.path.read_bytes() == b"hello doc"

    too_big = Receiver(tmp_path, limit_bytes=10)
    too_big.write(b"12345")
    with pytest.raises(TooLargeError):
        too_big.write(b"678901")
    assert sorted(p.name for p in tmp_path.iterdir()) == [incoming.path.name]  # nothing left


def test_blobs_are_stored_once_per_tenant(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path / "blobs")
    tenant, other = uuid.uuid4(), uuid.uuid4()

    def receive(data: bytes) -> Receiver:
        receiver = Receiver(store.incoming_dir(), limit_bytes=100)
        receiver.write(data)
        return receiver

    first = receive(b"same bytes").finish()
    store.put(tenant, first)
    again = receive(b"same bytes").finish()
    store.put(tenant, again)
    store.put(other, receive(b"same bytes").finish())
    assert not again.path.exists()  # the second copy was dropped
    with store.open(tenant, first.sha256) as handle:
        assert handle.read() == b"same bytes"
    assert store.path(tenant, first.sha256) != store.path(other, first.sha256)
    assert list(store.incoming_dir().iterdir()) == []
    store.delete(tenant, first.sha256)
    assert not store.path(tenant, first.sha256).exists()


def test_the_store_lists_its_files_and_removes_old_half_uploads(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path / "blobs")
    tenant = uuid.uuid4()

    def stored(data: bytes) -> Path:
        receiver = Receiver(store.incoming_dir(), limit_bytes=100)
        receiver.write(data)
        incoming = receiver.finish()
        store.put(tenant, incoming)
        return store.path(tenant, incoming.sha256)

    path = stored(b"some bytes")
    (path.parent / "notes.txt").write_bytes(b"not named as a blob")
    long_ago = datetime.now(UTC) - timedelta(days=3)
    os.utime(path, (long_ago.timestamp(), long_ago.timestamp()))
    sha256 = bytes.fromhex(path.name)
    assert [blob.sha256 for blob in store.stored(tenant)] == [sha256]
    before = store.modified(tenant, sha256)
    assert before is not None and before < datetime.now(UTC) - timedelta(days=2)
    assert stored(b"some bytes") == path  # the same bytes again: the file's time is renewed
    renewed = store.modified(tenant, sha256)
    assert renewed is not None and renewed > datetime.now(UTC) - timedelta(minutes=1)
    assert list(store.stored(uuid.uuid4())) == []
    assert store.modified(tenant, bytes(32)) is None

    old, fresh = store.incoming_dir() / "old.part", store.incoming_dir() / "fresh.part"
    old.write_bytes(b"half")
    fresh.write_bytes(b"half")
    os.utime(old, (long_ago.timestamp(), long_ago.timestamp()))
    assert store.remove_incoming(datetime.now(UTC) - timedelta(days=1)) == 1
    assert not old.exists()
    assert fresh.exists()


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("Karar 2026-35.pdf", "Karar 2026-35.pdf"),
        ("C:\\Users\\ayse\\Belgeler\\Rapor.docx", "Rapor.docx"),
        ("../../etc/passwd", "passwd"),
        ("bad\x00name\n.pdf", "badname.pdf"),
        ("   ", "file"),
        ("a" * 300 + ".pdf", "a" * 255),
    ],
)
def test_filenames_are_cleaned(given: str, expected: str) -> None:
    assert clean_filename(given) == expected


@pytest.mark.parametrize(
    ("given", "media_type", "expected"),
    [
        ("Karar 2026-35.pdf", MediaType.PDF, "Karar 2026-35.pdf"),
        ("KARAR.PDF", MediaType.PDF, "KARAR.PDF"),
        ("tarama.jpeg", MediaType.JPEG, "tarama.jpeg"),
        ("karar.html", MediaType.PDF, "karar.html.pdf"),
        ("rapor.pdf", MediaType.DOCX, "rapor.pdf.docx"),
        ("scan", MediaType.PNG, "scan.png"),
    ],
)
def test_a_name_keeps_or_gets_the_extension_of_its_content(
    given: str, media_type: MediaType, expected: str
) -> None:
    assert named_for(given, media_type) == expected


def test_an_added_extension_keeps_the_name_within_its_limit() -> None:
    named = named_for("a" * 255, MediaType.XLSX)
    assert (len(named), named[-5:]) == (255, ".xlsx")


def test_the_title_defaults_to_the_name_without_extension() -> None:
    assert default_title("Meclis Kararı 2026-16.pdf") == "Meclis Kararı 2026-16"
    assert default_title(".pdf") == ".pdf"
