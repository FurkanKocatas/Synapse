"""The knowledge package's public interface. Other packages import from here only."""

from synapse.knowledge.blobs import BlobStore, Incoming, LocalBlobStore, Receiver, TooLargeError
from synapse.knowledge.documents import (
    CollectionAccess,
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
from synapse.knowledge.ocr import PageReader, PageReading, TesseractEngine, TwoEngineReader
from synapse.knowledge.parsing import LightParser, Page, Parsed, ParseError, Parser
from synapse.knowledge.processing import Processor
from synapse.knowledge.rapid import RapidOcrEngine

__all__ = [
    "BlobStore",
    "CollectionAccess",
    "DocumentService",
    "DocumentSummary",
    "DuplicateError",
    "Incoming",
    "LightParser",
    "LocalBlobStore",
    "MediaType",
    "NotFoundError",
    "Page",
    "PageReader",
    "PageReading",
    "ParseError",
    "Parsed",
    "Parser",
    "Processor",
    "RapidOcrEngine",
    "Receiver",
    "StoredFile",
    "TesseractEngine",
    "TooLargeError",
    "TwoEngineReader",
    "UnsupportedFileError",
    "Uploaded",
    "Uploader",
    "VersionInfo",
    "detect",
]
