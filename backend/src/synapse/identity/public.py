"""The identity package's public interface. Other packages import from here only."""

from synapse.identity.passwords import PasswordPolicyError
from synapse.identity.repository import AuthLevel, Role
from synapse.identity.service import (
    CurrentSession,
    EnrollmentCompleted,
    IdentityService,
    IssuedSession,
    LoginRejected,
    NewAccount,
    SessionPolicy,
    TotpEnrollment,
)
from synapse.identity.totp import TotpCipher

__all__ = [
    "AuthLevel",
    "CurrentSession",
    "EnrollmentCompleted",
    "IdentityService",
    "IssuedSession",
    "LoginRejected",
    "NewAccount",
    "PasswordPolicyError",
    "Role",
    "SessionPolicy",
    "TotpCipher",
    "TotpEnrollment",
]
