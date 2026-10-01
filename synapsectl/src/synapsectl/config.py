"""``synapse.toml``: the single source of truth for an installation (ADR 0012).

Everything else (compose file, Caddyfile, environment) is rendered from it. Unknown keys are
rejected, so a typo cannot silently fall back to a default.
"""

import tomllib
import uuid
from enum import StrEnum
from pathlib import Path
from typing import Self

import tomli_w
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from synapsectl.models import Accelerator
from synapsectl.modules import BY_NAME

# Lower-case DNS labels separated by dots; the length limit is a separate constraint because
# pydantic's regular expressions do not support look-ahead.
_HOSTNAME = r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Tier(StrEnum):
    """Hardware tiers from docs/product/vision.md; they set memory limits and model choices."""

    CPU_16 = "cpu-16"
    CPU_32 = "cpu-32"
    GPU = "gpu"


class TlsMode(StrEnum):
    INTERNAL = "internal"  # Caddy's own certificate authority; its root is given to the IT team
    PROVIDED = "provided"  # a certificate from the customer's own PKI
    ACME = "acme"  # a public certificate, when the hostname is public


class Instance(Strict):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    # The tenant the installation serves; created with this ID during setup (ADR 0005).
    tenant_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    organization: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
    hostname: str = Field(pattern=_HOSTNAME, max_length=253)
    locale: str = Field(default="tr", pattern="^(tr|en)$")


class Tls(Strict):
    mode: TlsMode = TlsMode.INTERNAL
    # Contact address for the certificate authority (acme only).
    email: str | None = None
    # Paths on the host (provided only); copied into the secrets directory by render.
    certificate: Path | None = None
    private_key: Path | None = None

    @model_validator(mode="after")
    def _fields_for_mode(self) -> Self:
        if self.mode is TlsMode.ACME and not self.email:
            raise ValueError("tls.email is required for acme")
        if self.mode is TlsMode.PROVIDED and not (self.certificate and self.private_key):
            raise ValueError("tls.certificate and tls.private_key are required for provided")
        return self


class Network(Strict):
    http_port: int = Field(default=80, ge=1, le=65535)
    https_port: int = Field(default=443, ge=1, le=65535)
    # The containers' private network; change it only if it collides with the site's own.
    subnet: str = "172.29.0.0/24"


class Paths(Strict):
    secrets_dir: Path = Path("/etc/synapse/secrets")
    render_dir: Path = Path("/etc/synapse/rendered")


class Images(Strict):
    version: str = Field(default="dev", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class Models(Strict):
    """The model servers (ADR 0018): where their files are and what runs them."""

    # GGUF files on the host (synapsectl models fetch, or the offline bundle).
    dir: Path = Path("/var/lib/synapse/models")
    # vulkan: a GPU through Vulkan (integrated ones included), with /dev/dri passed in.
    accelerator: Accelerator = Accelerator.CPU
    # The host groups that own /dev/dri's devices (render, video); the servers run as 10001
    # and need them to open the GPU. Found by synapsectl init.
    gpu_groups: tuple[int, ...] = ()

    @model_validator(mode="after")
    def _groups_for_vulkan(self) -> Self:
        if self.accelerator is Accelerator.VULKAN and not self.gpu_groups:
            raise ValueError("models.gpu_groups is required for vulkan (the groups of /dev/dri)")
        return self


class Modules(Strict):
    enabled: tuple[str, ...] = ()

    @field_validator("enabled")
    @classmethod
    def _known_and_available(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for name in value:
            module = BY_NAME.get(name)
            if module is None:
                raise ValueError(f"unknown module: {name}")
            if not module.available:
                raise ValueError(f"module not available yet: {name}")
        return value


class SynapseConfig(Strict):
    instance: Instance
    hardware: Tier = Tier.CPU_16
    tls: Tls = Tls()
    network: Network = Network()
    paths: Paths = Paths()
    images: Images = Images()
    models: Models = Models()
    modules: Modules = Modules()


def load(path: Path) -> SynapseConfig:
    with path.open("rb") as handle:
        return SynapseConfig.model_validate(tomllib.load(handle))


def dump(config: SynapseConfig) -> str:
    data = config.model_dump(mode="json", exclude_none=True)
    return tomli_w.dumps(data)


def save(config: SynapseConfig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(config), encoding="utf-8")
