"""The ingestion jobs by name, so the API can enqueue them without importing any parser."""

from uuid import UUID

from synapse.jobs.queue import Job, JsonValue, Queue

PARSE_TASK = "ingest.parse_version"


def parse_job(document_id: UUID, version_id: UUID) -> Job:
    # One lock per document: its versions are processed one at a time, and a delete or a new
    # upload never races with parsing the same document.
    args: dict[str, JsonValue] = {"version_id": str(version_id)}
    return Job(PARSE_TASK, Queue.INGEST, args, lock=f"document:{document_id}")
