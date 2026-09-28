import uuid

from fastapi.testclient import TestClient

from synapse import __version__
from synapse.api.app import REQUEST_ID_HEADER, create_app
from synapse.kernel.config import Settings


def make_client() -> TestClient:
    return TestClient(create_app(Settings(log_format="console")))


def test_healthz_reports_version() -> None:
    response = make_client().get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_readyz_is_ok_without_dependencies() -> None:
    assert make_client().get("/readyz").status_code == 200


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


def test_docs_are_not_served_at_site_root() -> None:
    client = make_client()
    assert client.get("/docs").status_code == 404
    assert client.get("/api/docs").status_code == 200
