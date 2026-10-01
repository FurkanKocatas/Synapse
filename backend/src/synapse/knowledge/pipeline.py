"""The ingestion jobs by name, so the API can enqueue them without importing any parser."""

from uuid import UUID

from synapse.jobs.queue import Job, JsonValue, Queue

PARSE_TASK = "ingest.parse_version"
OCR_TASK = "ingest.ocr_version"
EMBED_TASK = "ingest.embed_version"


def parse_job(document_id: UUID, version_id: UUID) -> Job:
    # One lock per document: its versions are processed one at a time, and a delete or a new
    # upload never races with parsing the same document.
    args: dict[str, JsonValue] = {"version_id": str(version_id)}
    return Job(PARSE_TASK, Queue.INGEST, args, lock=f"document:{document_id}")


def ocr_job(document_id: UUID, version_id: UUID) -> Job:
    # Its own queue, so a big machine can give OCR processes of their own; the same lock as
    # parsing.
    args: dict[str, JsonValue] = {"version_id": str(version_id)}
    return Job(OCR_TASK, Queue.OCR, args, lock=f"document:{document_id}")


def embed_job(document_id: UUID, version_id: UUID) -> Job:
    # Its own queue too: on a machine with a GPU the embedding server is the bottleneck, not the
    # worker's CPU.
    args: dict[str, JsonValue] = {"version_id": str(version_id)}
    return Job(EMBED_TASK, Queue.EMBED, args, lock=f"document:{document_id}")
