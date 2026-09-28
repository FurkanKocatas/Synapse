"""Every route is either explicitly public or requires a session (ADR 0007).

A route that forgets its dependency would otherwise be open to everyone without anyone noticing.
"""

from collections.abc import Callable, Iterable, Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute

from synapse.api.app import create_app
from synapse.api.deps import _current_session, public_endpoint, require
from synapse.authz.public import UnknownPermissionError
from synapse.kernel.config import Settings


def calls(dependant: Dependant) -> Iterator[Callable[..., Any]]:
    for dependency in dependant.dependencies:
        if dependency.call is not None:
            yield dependency.call
        yield from calls(dependency)


def flatten(routes: Iterable[BaseRoute]) -> Iterator[APIRoute]:
    """Every endpoint, including those of included routers.

    FastAPI 0.141 keeps included routers as nested objects instead of copying their routes, and
    exposes them only through a private class. If that changes again, the next test fails
    loudly instead of this one passing without checking anything.
    """
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif (nested := getattr(route, "original_router", None)) is not None:
            yield from flatten(nested.routes)


def api_routes() -> list[APIRoute]:
    app = create_app(Settings(log_format="console", api_docs=True))
    return list(flatten(app.routes))


def unguarded(routes: Iterable[APIRoute]) -> list[str]:
    found = []
    for route in routes:
        dependencies = set(calls(route.dependant))
        is_public = public_endpoint in dependencies
        needs_session = _current_session in dependencies
        if is_public == needs_session:  # neither, or (contradictory) both
            found.append(f"{sorted(route.methods or [])} {route.path}")
    return found


def test_every_route_is_public_or_needs_a_session() -> None:
    assert unguarded(api_routes()) == []


def test_the_inventory_catches_a_route_without_a_guard() -> None:
    app = FastAPI()

    @app.get("/forgotten")
    async def forgotten() -> None:
        """A route whose author forgot the session dependency."""

    assert unguarded(flatten(app.routes)) == ["['GET'] /forgotten"]


def test_the_inventory_sees_the_routes_it_should() -> None:
    paths = {route.path for route in api_routes()}
    assert {"/api/auth/login", "/api/auth/session", "/api/audit/status", "/healthz"} <= paths


def test_a_misspelled_permission_fails_when_the_route_is_defined() -> None:
    with pytest.raises(UnknownPermissionError):
        require("audit.raed")
