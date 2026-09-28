"""Stack smoke step: register a passkey and sign in with it through the web front.

Uses the backend tests' software authenticator, so the real images, the proxy and
SYNAPSE_PUBLIC_URL are exercised together. Standard library HTTP only; the session cookie is
handled by hand because it is a Secure cookie on plain-HTTP localhost.

Usage (from the repository root, inside the backend environment):
    uv run --directory backend python ../tools/smoke_passkey.py BASE_URL ORIGIN EMAIL PASSWORD_FILE
"""

import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from tests.soft_authenticator import SoftAuthenticator


class Client:
    def __init__(self, base: str) -> None:
        self.base = base
        self.cookie: str | None = None
        self.csrf: str | None = None

    def post(self, path: str, body: object | None = None) -> Any:
        headers = {"Content-Type": "application/json", "X-Synapse-Client": "web"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        if self.csrf:
            headers["X-Synapse-CSRF"] = self.csrf
        data = json.dumps(body if body is not None else {}).encode()
        request = urllib.request.Request(self.base + path, data=data, headers=headers)  # noqa: S310  (local URL from the caller)
        with urllib.request.urlopen(request) as response:  # noqa: S310
            cookie = response.headers.get("Set-Cookie")
            if cookie:
                self.cookie = cookie.split(";", 1)[0]
            payload = json.loads(response.read() or b"null")
        if isinstance(payload, dict) and "csrf_token" in payload:
            self.csrf = payload["csrf_token"]
        return payload


def expect(what: object, *, holds: bool) -> None:
    if not holds:
        raise SystemExit(f"passkey smoke step failed: {what}")


def main() -> None:
    base, origin, email, password_file = sys.argv[1:5]
    password = Path(password_file).read_text(encoding="utf-8")
    device = SoftAuthenticator(origin=origin, rp_id="localhost")

    first = Client(base)
    first.post("/api/auth/login", {"email": email, "password": password})
    options = first.post("/api/auth/passkeys/registration-options")
    registered = first.post(
        "/api/auth/passkeys", {"credential": device.create(options), "name": "Smoke"}
    )
    expect(registered, holds=bool(registered["recovery_codes"]))

    second = Client(base)
    level = second.post("/api/auth/login", {"email": email, "password": password})["auth_level"]
    expect(level, holds=level == "pending_mfa")
    challenge = second.post("/api/auth/mfa/passkey/options")
    done = second.post("/api/auth/mfa/passkey", {"credential": device.get(challenge)})
    expect(done, holds=done["auth_level"] == "full")
    print("passkey registered and used through the web front")


if __name__ == "__main__":
    main()
