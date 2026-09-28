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
from synapse.knowledge.parsing import LightParser, Page, Parsed, ParseError, Parser
from synapse.knowledge.processing import Processor

__all__ = [
    "BlobStore",
    "DocumentService",
    "DocumentSummary",
    "DuplicateError",
    "Incoming",
    "LightParser",
    "LocalBlobStore",
    "MediaType",
    "NotFoundError",
    "Page",
    "ParseError",
    "Parsed",
    "Parser",
    "Processor",
    "Receiver",
    "StoredFile",
    "TooLargeError",
    "UnsupportedFileError",
    "Uploaded",
    "Uploader",
    "VersionInfo",
    "detect",
]
