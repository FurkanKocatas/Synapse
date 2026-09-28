import base64

from synapse.dbadmin.scram import ITERATIONS, scram_sha256_verifier


def test_verifier_has_postgres_format() -> None:
    verifier = scram_sha256_verifier("password", salt=b"0123456789abcdef")
    method, parameters, keys = verifier.split("$")
    iterations, salt = parameters.split(":")
    stored_key, server_key = keys.split(":")
    assert method == "SCRAM-SHA-256"
    assert int(iterations) == ITERATIONS
    assert base64.b64decode(salt) == b"0123456789abcdef"
    assert len(base64.b64decode(stored_key)) == 32
    assert len(base64.b64decode(server_key)) == 32


def test_same_salt_gives_same_verifier_and_new_salt_differs() -> None:
    salt = b"fixed-salt-16by."
    assert scram_sha256_verifier("pw", salt=salt) == scram_sha256_verifier("pw", salt=salt)
    assert scram_sha256_verifier("pw") != scram_sha256_verifier("pw")


def test_password_does_not_appear_in_verifier() -> None:
    assert "hunter2" not in scram_sha256_verifier("hunter2")
