"""The optional modules an installation can enable (docs/product/modules.md).

A module listed here but not yet available can be shown in the wizard, so the installer and the
customer see what is coming, but it cannot be enabled.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Module:
    name: str
    title: str
    description: str
    available: bool


CATALOGUE = (
    Module(
        name="reports",
        title="Reports",
        description="Structured reports from documents, every figure cited",
        available=False,
    ),
    Module(
        name="specifications",
        title="Specifications",
        description="Drafting and compliance review of technical specifications",
        available=False,
    ),
    Module(
        name="translation",
        title="Translation",
        description="Document and text translation with glossaries",
        available=False,
    ),
    Module(
        name="calendar",
        title="Calendar",
        description="Reminders and deadlines taken from documents",
        available=False,
    ),
)

BY_NAME = {module.name: module for module in CATALOGUE}
