"""Process configuration.

Every setting comes from the environment with the ``SYNAPSE_`` prefix. In production the
values are rendered by ``synapsectl`` from ``synapse.toml`` (see ADR 0012); they are never
edited by hand on a server.

There is deliberately no "environment" or "debug" switch that changes security behaviour:
the same code paths run in development and production (ADR 0006).
"""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LogFormat(StrEnum):
    JSON = "json"
    CONSOLE = "console"


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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, read once from the environment."""
    return Settings()
