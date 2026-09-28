"""File type detection from the bytes, never from the name (ADR 0010).

A file called ``report.pdf`` may be anything. The type decides which parser runs, so it comes
from the content: magic numbers, and for Office files the main part declared in the package's
``[Content_Types].xml``.
"""

import zipfile
from enum import StrEnum
from pathlib import Path

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException


class MediaType(StrEnum):
    PDF = "application/pdf"
    DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    PNG = "image/png"
    JPEG = "image/jpeg"
    TIFF = "image/tiff"


class UnsupportedFileError(ValueError):
    """Not a type Synapse can read; ``reason`` is a stable code for the interface."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# The Office main parts, as declared in [Content_Types].xml. Macro-enabled variants (.docm and
# the like) declare different types and are refused.
_OFFICE_MAIN_PARTS = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml": (
        MediaType.DOCX
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml": MediaType.XLSX,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml": (
        MediaType.PPTX
    ),
}
_CONTENT_TYPES_LIMIT = 1 << 20
_OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")
_HEAD_BYTES = 1024


def detect(path: Path) -> MediaType:
    with path.open("rb") as handle:
        head = handle.read(_HEAD_BYTES)
    # The PDF header may follow some leading bytes; readers accept it within the first 1024.
    if b"%PDF-" in head:
        return MediaType.PDF
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return MediaType.PNG
    if head.startswith(b"\xff\xd8\xff"):
        return MediaType.JPEG
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return MediaType.TIFF
    if head.startswith(b"PK\x03\x04"):
        return _office_type(path)
    if head.startswith(_OLE_MAGIC):
        # Legacy .doc, .xls and .ppt, and also password-protected Office files.
        raise UnsupportedFileError("legacy_office")
    raise UnsupportedFileError("unknown_type")


def _office_type(path: Path) -> MediaType:
    try:
        with zipfile.ZipFile(path) as package:
            info = package.getinfo("[Content_Types].xml")
            if info.file_size > _CONTENT_TYPES_LIMIT:
                raise UnsupportedFileError("unknown_type")
            content_types = package.read(info)
    except (KeyError, zipfile.BadZipFile) as error:
        raise UnsupportedFileError("unknown_type") from error
    try:
        # defusedxml refuses entity tricks; uploads are untrusted input.
        root = ElementTree.fromstring(content_types)
    except (ElementTree.ParseError, DefusedXmlException) as error:
        raise UnsupportedFileError("unknown_type") from error
    for element in root:
        media = _OFFICE_MAIN_PARTS.get(element.get("ContentType", ""))
        if media is not None:
            return media
    raise UnsupportedFileError("unknown_type")
