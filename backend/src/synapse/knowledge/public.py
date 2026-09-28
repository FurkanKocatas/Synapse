"""The knowledge package's public interface. Other packages import from here only."""

from synapse.knowledge.blobs import BlobStore, Incoming, LocalBlobStore, Receiver, TooLargeError
from synapse.knowledge.documents import (
    DocumentService,
    DocumentSummary,
    DuplicateError,
    NotFoundError,
    StoredFile,
    Uploaded,
    Uploader,
    VersionInfo,
)
from synapse.knowledge.filetypes import MediaType, UnsupportedFileError, detect

__all__ = [
    "BlobStore",
    "DocumentService",
    "DocumentSummary",
    "DuplicateError",
    "Incoming",
    "LocalBlobStore",
    "MediaType",
    "NotFoundError",
    "Receiver",
    "StoredFile",
    "TooLargeError",
    "UnsupportedFileError",
    "Uploaded",
    "Uploader",
    "VersionInfo",
    "detect",
]
