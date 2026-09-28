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


def test_recovery_code_normalization_accepts_user_formatting() -> None:
    code = recovery.new_codes()[0]
    typed = " " + code.lower().replace("-", " ") + " "
    assert recovery.hash_code(typed) == recovery.hash_code(code)
