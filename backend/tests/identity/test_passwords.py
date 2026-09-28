import pytest
from argon2 import PasswordHasher

from synapse.identity.passwords import (
    MAX_LENGTH,
    MIN_LENGTH_SINGLE_FACTOR,
    MIN_LENGTH_WITH_MFA,
    PasswordPolicyError,
    hash_password,
    needs_rehash,
    validate_password,
    verify_password,
)


def test_hash_verifies_and_is_argon2id() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "correct horse battery staple")
    assert not verify_password(hashed, "correct horse battery stapler")


def test_missing_hash_never_verifies() -> None:
    assert not verify_password(None, "anything at all")


def test_oversized_password_is_rejected_without_hashing() -> None:
    assert not verify_password(hash_password("x" * 20), "x" * (MAX_LENGTH + 1))


def test_current_parameters_need_no_rehash() -> None:
    assert not needs_rehash(hash_password("some long passphrase"))


def test_weaker_parameters_need_rehash() -> None:
    old = PasswordHasher(time_cost=1, memory_cost=8 * 1024, parallelism=1).hash("pw long enough")
    assert needs_rehash(old)


@pytest.mark.parametrize(
    ("length", "mfa", "allowed"),
    [
        (MIN_LENGTH_SINGLE_FACTOR - 1, False, False),
        (MIN_LENGTH_SINGLE_FACTOR, False, True),
        (MIN_LENGTH_WITH_MFA - 1, True, False),
        (MIN_LENGTH_WITH_MFA, True, True),
        (MAX_LENGTH, False, True),
        (MAX_LENGTH + 1, False, False),
    ],
)
def test_length_rules(length: int, *, mfa: bool, allowed: bool) -> None:
    password = "k" * length
    if allowed:
        validate_password(password, mfa_enabled=mfa, context_words=[])
    else:
        with pytest.raises(PasswordPolicyError):
            validate_password(password, mfa_enabled=mfa, context_words=[])


def test_no_composition_rules() -> None:
    # Only lower-case letters and spaces: fine under NIST SP 800-63B-4.
    validate_password("bahar geldi kuşlar öter", mfa_enabled=False, context_words=[])


def test_unicode_and_spaces_are_accepted() -> None:
    validate_password("İstanbul'da güzel bir sabah", mfa_enabled=False, context_words=[])


def test_context_words_are_rejected_case_insensitively() -> None:
    with pytest.raises(PasswordPolicyError) as error:
        validate_password(
            "my name is AYSEGUL and I like tea", mfa_enabled=False, context_words=["aysegul"]
        )
    assert error.value.code == "password_contains_context"


def test_short_context_words_are_ignored() -> None:
    validate_password("a long passphrase with ab inside", mfa_enabled=False, context_words=["ab"])
