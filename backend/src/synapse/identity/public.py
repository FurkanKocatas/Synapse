"""The identity package's public interface. Other packages import from here only."""

from synapse.identity.accounts import (
    Account,
    AccountService,
    LastAdministratorError,
    OwnAccountError,
)
from synapse.identity.passwords import PasswordPolicyError
from synapse.identity.profile import (
    Locale,
    ProfileService,
    SessionInfo,
    TooManyAttemptsError,
    WrongPasswordError,
)
from synapse.identity.repository import AuthLevel, Role
from synapse.identity.service import (
    AccountExistsError,
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
    "Account",
    "AccountExistsError",
    "AccountService",
    "AuthLevel",
    "CurrentSession",
    "EnrollmentCompleted",
    "IdentityService",
    "IssuedSession",
    "LastAdministratorError",
    "Locale",
    "LoginRejected",
    "NewAccount",
    "OwnAccountError",
    "PasswordPolicyError",
    "ProfileService",
    "Role",
    "SessionInfo",
    "SessionPolicy",
    "TooManyAttemptsError",
    "TotpCipher",
    "TotpEnrollment",
    "WrongPasswordError",
]
