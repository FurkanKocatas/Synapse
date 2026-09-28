"""The authorization package's public interface. Other packages import from here only."""

from synapse.authz.checks import (
    ROLE_PERMISSIONS,
    DocumentPermission,
    UnknownPermissionError,
    accessible_document_ids,
    can_access_document,
    check_known,
    role_has_permission,
)

__all__ = [
    "ROLE_PERMISSIONS",
    "DocumentPermission",
    "UnknownPermissionError",
    "accessible_document_ids",
    "can_access_document",
    "check_known",
    "role_has_permission",
]
