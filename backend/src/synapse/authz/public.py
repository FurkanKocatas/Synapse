"""The authorization package's public interface. Other packages import from here only."""

from synapse.authz import management
from synapse.authz.checks import (
    ROLE_PERMISSIONS,
    DocumentPermission,
    UnknownPermissionError,
    accessible_document_ids,
    can_access_document,
    check_known,
    role_has_permission,
)
from synapse.authz.management import (
    Actor,
    Collection,
    ConflictError,
    Grant,
    Group,
    Member,
    NotFoundError,
    PrincipalType,
)

__all__ = [
    "ROLE_PERMISSIONS",
    "Actor",
    "Collection",
    "ConflictError",
    "DocumentPermission",
    "Grant",
    "Group",
    "Member",
    "NotFoundError",
    "PrincipalType",
    "UnknownPermissionError",
    "accessible_document_ids",
    "can_access_document",
    "check_known",
    "management",
    "role_has_permission",
]
