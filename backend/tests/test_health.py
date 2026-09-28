import uuid

from fastapi.testclient import TestClient
from starlette.requests import Request

from synapse import __version__
from synapse.api.app import REQUEST_ID_HEADER, create_app
from synapse.api.deps import client_ip
from synapse.kernel.config import Settings


def make_client() -> TestClient:
    return TestClient(create_app(Settings(log_format="console")))


def test_healthz_reports_version() -> None:
    response = make_client().get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_request_id_is_generated_when_missing() -> None:
    response = make_client().get("/healthz")
    uuid.UUID(response.headers[REQUEST_ID_HEADER])


def test_valid_request_id_is_propagated() -> None:
    request_id = str(uuid.uuid4())
    response = make_client().get("/healthz", headers={REQUEST_ID_HEADER: request_id})
    assert response.headers[REQUEST_ID_HEADER] == request_id


def test_invalid_request_id_is_replaced() -> None:
    # Arbitrary client text must never end up in log lines as a request ID.
    response = make_client().get("/healthz", headers={REQUEST_ID_HEADER: "evil\nforged-line"})
    returned = response.headers[REQUEST_ID_HEADER]
    assert returned != "evil\nforged-line"
    uuid.UUID(returned)


def test_docs_are_off_by_default_and_never_at_the_site_root() -> None:
    assert make_client().get("/api/docs").status_code == 404
    with_docs = TestClient(create_app(Settings(log_format="console", api_docs=True)))
    assert with_docs.get("/api/docs").status_code == 200
    assert with_docs.get("/docs").status_code == 404


def test_client_ip_accepts_only_ip_addresses() -> None:
    def request_from(host: str) -> Request:
        return Request({"type": "http", "client": (host, 1234), "headers": []})

    assert client_ip(request_from("192.0.2.1")) == "192.0.2.1"
    assert client_ip(request_from("2001:db8::1")) == "2001:db8::1"
    assert client_ip(request_from("testclient")) is None
    assert client_ip(Request({"type": "http", "client": None, "headers": []})) is None
