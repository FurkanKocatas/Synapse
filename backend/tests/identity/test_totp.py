import uuid

import pyotp
import pytest
from cryptography.exceptions import InvalidTag

from synapse.identity.totp import (
    STEP_SECONDS,
    TotpCipher,
    new_secret,
    provisioning_uri,
    verify_code,
)

NOW = 1_790_000_000.0  # a fixed moment, so tests do not depend on the clock


def code_at(secret: str, moment: float) -> str:
    return pyotp.TOTP(secret).at(int(moment))


def test_current_code_is_accepted_with_its_step() -> None:
    secret = new_secret()
    accepted = verify_code(secret, code_at(secret, NOW), last_used_step=None, now=NOW)
    assert accepted is not None
    assert accepted.step == int(NOW // STEP_SECONDS)


def test_adjacent_steps_are_accepted_for_clock_drift() -> None:
    secret = new_secret()
    assert verify_code(secret, code_at(secret, NOW - STEP_SECONDS), last_used_step=None, now=NOW)
    assert verify_code(secret, code_at(secret, NOW + STEP_SECONDS), last_used_step=None, now=NOW)


def test_distant_codes_are_rejected() -> None:
    secret = new_secret()
    assert (
        verify_code(secret, code_at(secret, NOW - 5 * STEP_SECONDS), last_used_step=None, now=NOW)
        is None
    )


def test_a_used_code_cannot_be_replayed() -> None:
    secret = new_secret()
    code = code_at(secret, NOW)
    accepted = verify_code(secret, code, last_used_step=None, now=NOW)
    assert accepted is not None
    assert verify_code(secret, code, last_used_step=accepted.step, now=NOW) is None


@pytest.mark.parametrize("code", ["", "12345", "1234567", "abcdef"])
def test_malformed_codes_are_rejected(code: str) -> None:
    assert verify_code(new_secret(), code, last_used_step=None, now=NOW) is None


def test_code_with_spaces_is_accepted() -> None:
    secret = new_secret()
    code = code_at(secret, NOW)
    assert verify_code(secret, f"{code[:3]} {code[3:]}", last_used_step=None, now=NOW)


def test_cipher_round_trip_is_bound_to_user() -> None:
    cipher = TotpCipher(b"k" * 32)
    owner, other = uuid.uuid4(), uuid.uuid4()
    ciphertext = cipher.encrypt(owner, "JBSWY3DPEHPK3PXP")
    assert cipher.decrypt(owner, ciphertext) == "JBSWY3DPEHPK3PXP"
    with pytest.raises(InvalidTag):
        cipher.decrypt(other, ciphertext)


def test_cipher_rejects_short_keys() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        TotpCipher(b"short")


def test_provisioning_uri_names_issuer_and_account() -> None:
    uri = provisioning_uri(new_secret(), "ayse@example.org")
    assert uri.startswith("otpauth://totp/Synapse:ayse%40example.org?")
    assert "issuer=Synapse" in uri
