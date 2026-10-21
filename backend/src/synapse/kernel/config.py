"""Process configuration.

Every setting comes from the environment with the ``SYNAPSE_`` prefix. In production the
values are rendered by ``synapsectl`` from ``synapse.toml`` (see ADR 0012); they are never
edited by hand on a server.

There is deliberately no "environment" or "debug" switch that changes security behaviour:
the same code paths run in development and production (ADR 0006).
"""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from synapse.kernel.database import ConnectionSettings


class LogFormat(StrEnum):
    JSON = "json"
    CONSOLE = "console"


# A model server's address: http or https, a host and a port, no path.
MODEL_URL = r"^https?://[A-Za-z0-9.-]+(:\d+)?$"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SYNAPSE_", frozen=True, extra="ignore")

    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR)$")
    # JSON for containers; console output is easier to read while developing locally.
    log_format: LogFormat = LogFormat.JSON

    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    # Addresses whose X-Forwarded-* headers are trusted: the reverse proxy only. Anything
    # else could spoof client IPs, which feed rate limiting and the audit log.
    trusted_proxy_ips: str = "127.0.0.1"
    # The interactive API documentation and schema. Off by default: publishing the full API
    # surface helps attackers more than users. Enable on development machines.
    api_docs: bool = False

    # Each process connects as its own role (ADR 0013); the password is read from a file.
    db_host: str = "127.0.0.1"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = "synapse"
    db_user: str = "synapse_api"
    db_password_file: Path = Path("/run/secrets/db_password")

    # On-prem runs as a single tenant; the installer writes its ID here (ADR 0005).
    tenant_id: UUID | None = None
    csrf_key_file: Path = Path("/run/secrets/csrf_key")
    totp_key_file: Path = Path("/run/secrets/totp_key")
    # Ed25519 seed that signs audit checkpoints (ADR 0008).
    audit_signing_key_file: Path = Path("/run/secrets/audit_signing_key")
    # Audit retention (ADR 0022): events, and a chat question's text, are kept this many days.
    # synapse db migrate writes them where audit_prune() reads them; the floors are the
    # database's own too.
    audit_keep_events_days: int = Field(default=365, ge=90, le=3650)
    audit_keep_question_days: int = Field(default=183, ge=30, le=3650)
    session_idle_minutes: int = Field(default=30, ge=5, le=24 * 60)
    session_absolute_hours: int = Field(default=12, ge=1, le=24 * 30)
    # Uploaded files (ADR 0003): a local directory, normally a Docker volume.
    blob_dir: Path = Path("/var/lib/synapse/blobs")
    upload_max_mb: int = Field(default=100, ge=1, le=2048)
    # OCR (docs/benchmarks/ocr.md). The application image ships Tesseract's "best" models and
    # sets this; unset means Tesseract's own models.
    ocr_tessdata_dir: Path | None = None
    # Threads the OCR engines' onnxruntime may use (PP-OCRv6, or RapidOCR where it gives the
    # second reading). A worker reads one page at a time with them; PP-OCRv6 reads a page about
    # three times as fast with four as with one (docs/benchmarks/ocr.md).
    ocr_threads: int = Field(default=4, ge=1, le=16)
    # PP-OCRv6's model directory (knowledge/ppocr.py). Set, PP-OCRv6 with the Turkish character
    # language model gives the text of pages that need OCR, and Tesseract reads their identifiers
    # a second time; with PP-OCRv5's Latin recogniser in it too, the three readings are voted
    # (ADR 0020). The application image sets it (ADR 0019). Unset, Tesseract gives the text
    # and RapidOCR the second reading.
    ocr_ppocr_dir: Path | None = None
    # Model servers (ADR 0009, ADR 0018): llama.cpp on the internal network, one per role, each
    # with its own API key. A role without a URL has no model: ingestion then stores no vectors.
    embed_url: str | None = Field(default=None, pattern=MODEL_URL)
    embed_key_file: Path = Path("/run/secrets/embed_key")
    rerank_url: str | None = Field(default=None, pattern=MODEL_URL)
    rerank_key_file: Path = Path("/run/secrets/rerank_key")
    chat_url: str | None = Field(default=None, pattern=MODEL_URL)
    chat_key_file: Path = Path("/run/secrets/chat_key")
    # The longest a model call may take; a chat answer on the CPU alone takes about a minute.
    model_timeout_seconds: float = Field(default=180, ge=1, le=900)
    # Refusal before generation (ADR 0010, query rule 6): a question whose best reranker score
    # (a logit of bge-reranker-v2-m3) is below this is answered "not found" without calling the
    # chat model. Calibrated on the golden set (docs/benchmarks/refusal.md): at 1.0, with the
    # model's own refusals, 31 of the 34 unanswerable questions are refused and no correct
    # answer is lost.
    chat_refuse_below: float = Field(default=1.0, ge=-100, le=100)
    # The sources an answer is written from (ADR 0010, query rule 7): six on the CPU alone,
    # where the first token already takes about a minute, and eight with the model on a GPU,
    # where a decision that ranked below the petitions comes in (docs/benchmarks/answers.md,
    # "Who asked, who decided"). The installer sets it by the accelerator.
    chat_sources: int = Field(default=6, ge=1, le=12)
    # The sources' budget in the chat model's tokens (chat/answering.py, SOURCE_TOKENS). On the
    # CPU alone the model reads a prompt at about 65 tokens a second, so the first token waits on
    # the sources' length; the default keeps it within ADR 0009's minute there, and the installer
    # writes 5,600 with the model on a GPU (docs/benchmarks/answers.md, "On the CPU alone").
    # The fusion's first chunks the reranker reads (knowledge/search.py, RERANK_TOP). More of them
    # find more of the evidence, most for questions asked in other words, at about 0.3 seconds a
    # chunk on an integrated GPU and far more on the CPU alone, where it stays at 15; the
    # installer writes more with the model on a GPU (docs/benchmarks/embeddings.md, "Reranking
    # more").
    search_rerank_top: int = Field(default=15, ge=5, le=100)
    chat_source_tokens: int = Field(default=2400, ge=500, le=5600)
    # A message whose search finds nothing good enough and that the chat model judges to be a
    # question of general knowledge (not about the organisation) or a request for help with
    # writing is answered from general knowledge, marked as not resting on the documents. Off:
    # such a message is refused like a question the documents do not answer. Greetings and
    # thanks are answered either way.
    chat_general_answers: bool = True
    # The classic chat: a plain conversation with the chat model, beside the assistant over the
    # documents. Off: only the assistant over the documents is offered.
    chat_classic: bool = True
    # The address users open, such as https://synapse.example.org. Passkeys are bound to its
    # host name, so they stop working if it changes; unset means passkeys are unavailable.
    public_url: str | None = Field(
        default=None, pattern=r"^(https://[^/:?#]+(:\d+)?|http://localhost(:\d+)?)$"
    )

    @field_validator(
        "tenant_id",
        "public_url",
        "ocr_tessdata_dir",
        "ocr_ppocr_dir",
        "embed_url",
        "rerank_url",
        "chat_url",
        mode="before",
    )
    @classmethod
    def _empty_means_unset(cls, value: object) -> object:
        # Environment files commonly carry "NAME=" for a value not filled in yet.
        return None if value == "" else value

    @model_validator(mode="after")
    def _question_within_events(self) -> Self:
        if self.audit_keep_question_days > self.audit_keep_events_days:
            raise ValueError("audit_keep_question_days must not exceed audit_keep_events_days")
        return self

    def database(self, application_name: str) -> ConnectionSettings:
        return ConnectionSettings(
            host=self.db_host,
            port=self.db_port,
            dbname=self.db_name,
            user=self.db_user,
            password_file=self.db_password_file,
            application_name=application_name,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, read once from the environment."""
    return Settings()
