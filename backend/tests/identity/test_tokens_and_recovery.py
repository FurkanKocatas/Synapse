import hashlib
import uuid

from synapse.identity import recovery
from synapse.identity.tokens import (
    csrf_token,
    csrf_token_matches,
    hash_session_token,
    new_session_token,
)


def test_session_tokens_are_random_and_hash_to_32_bytes() -> None:
    first, second = new_session_token(), new_session_token()
    assert first != second
    assert len(hash_session_token(first)) == 32


def test_csrf_token_is_bound_to_key_and_session() -> None:
    key, other_key = b"k" * 32, b"o" * 32
    session, other_session = hash_session_token("a"), hash_session_token("b")
    token = csrf_token(key, session)
    assert csrf_token_matches(key, session, token)
    assert not csrf_token_matches(other_key, session, token)
    assert not csrf_token_matches(key, other_session, token)


def test_recovery_codes_are_unique_and_formatted() -> None:
    codes = recovery.new_codes()
    assert len(codes) == recovery.CODE_COUNT
    assert len(set(codes)) == len(codes)
    assert all(len(code) == 19 and code.count("-") == 3 for code in codes)


def test_recovery_codes_are_stored_salted_and_found_as_users_type_them() -> None:
    code, other = recovery.new_codes()[:2]
    stored = recovery.hash_code(code)
    assert stored.startswith("$argon2id$") and stored != recovery.hash_code(code)
    held = [(uuid.uuid4(), recovery.hash_code(other)), (uuid.uuid4(), stored)]
    typed = " " + code.lower().replace("-", " ") + " "
    assert recovery.find(held, typed) == held[1][0]
    assert recovery.find(held, recovery.new_codes()[0]) is None


def test_only_what_looks_like_a_code_is_tried() -> None:
    assert recovery.looks_like_a_code("abcd efgh-ijkl-mnop")
    # A TOTP code, a short one, and letters no code has (which once failed to encode).
    for typed in ("123456", "ABCD-EFGH-IJKL", "ÇĞİÖ-ŞÜAB-CDEF-GHIJ"):
        assert not recovery.looks_like_a_code(typed)
        assert recovery.find([(uuid.uuid4(), recovery.hash_code(typed))], typed) is None


def test_a_code_issued_before_argon2_still_works() -> None:
    code = recovery.new_codes()[0]
    legacy = hashlib.sha256(recovery.normalize(code).encode("ascii")).hexdigest()
    assert recovery.matches(legacy, code.lower())
    assert not recovery.matches(legacy, recovery.new_codes()[0])
