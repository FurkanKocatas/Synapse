"""The interactive part of ``synapsectl init``: asks the installer for what cannot be guessed.

Every answer has a sensible default shown in brackets, so pressing Enter through the wizard
produces a working local installation.
"""

import os
import re
import unicodedata
from collections.abc import Callable

from synapsectl.config import Instance, SynapseConfig, Tier, Tls, TlsMode
from synapsectl.modules import CATALOGUE

Ask = Callable[[str], str]

_TURKISH = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


def slug_of(name: str) -> str:
    """A tenant slug from an organization name: ``Çankırı Belediyesi`` -> ``cankiri-belediyesi``."""
    ascii_name = unicodedata.normalize("NFKD", name.translate(_TURKISH)).encode("ascii", "ignore")
    words = re.findall(r"[a-z0-9]+", ascii_name.decode().lower())
    return "-".join(words)[:63].strip("-") or "organization"


def suggested_tier() -> Tier:
    try:
        memory_gib = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
    except ValueError, OSError:
        return Tier.CPU_16
    return Tier.CPU_32 if memory_gib >= 30 else Tier.CPU_16  # noqa: PLR2004


def _choose(ask: Ask, question: str, default: str) -> str:
    answer = ask(f"{question} [{default}]: ").strip()
    return answer or default


def run(ask: Ask = input) -> SynapseConfig:
    print("Synapse installation\n")
    organization = _choose(ask, "Organization name", "Example Organization")
    slug = _choose(ask, "Short name (lower case, digits, dashes)", slug_of(organization))
    hostname = _choose(ask, "Host name users will open", f"synapse.{slug}.local")
    locale = _choose(ask, "Default language (tr, en)", "tr")
    tier = Tier(_choose(ask, "Hardware tier (cpu-16, cpu-32, gpu)", suggested_tier().value))

    mode = TlsMode(_choose(ask, "TLS (internal, provided, acme)", TlsMode.INTERNAL.value))
    if mode is TlsMode.INTERNAL:
        tls = Tls(mode=mode)
    elif mode is TlsMode.ACME:
        tls = Tls(mode=mode, email=_choose(ask, "Contact email for the certificate", ""))
    else:
        tls = Tls.model_validate(
            {
                "mode": mode,
                "certificate": _choose(ask, "Certificate file (PEM)", ""),
                "private_key": _choose(ask, "Private key file (PEM)", ""),
            }
        )

    print("\nOptional modules")
    for module in CATALOGUE:
        state = "available" if module.available else "coming soon"
        print(f"  {module.name:<16} {module.title}: {module.description} ({state})")
    available = [module.name for module in CATALOGUE if module.available]
    chosen: tuple[str, ...] = ()
    if available:
        answer = _choose(ask, "Modules to enable, separated by commas", "")
        chosen = tuple(name.strip() for name in answer.split(",") if name.strip())

    return SynapseConfig.model_validate(
        {
            "instance": Instance(
                organization=organization, slug=slug, hostname=hostname, locale=locale
            ),
            "hardware": tier,
            "tls": tls,
            "modules": {"enabled": chosen},
        }
    )
