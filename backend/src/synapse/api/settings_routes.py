"""``/api/admin/settings``: the organisation's settings, for administrators."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Request

from synapse.api.deps import client_ip, require
from synapse.identity.public import CurrentSession
from synapse.organization.public import OrganizationSettings, SettingsService

router = APIRouter(prefix="/api/admin", tags=["admin"])

ManageSettings = Annotated[CurrentSession, require("settings.manage")]


def _service(request: Request) -> SettingsService:
    service: SettingsService = request.app.state.organization
    return service


@router.get("/settings")
async def settings(_session: ManageSettings, request: Request) -> OrganizationSettings:
    return await _service(request).get()


# Only the keys sent change.
@router.patch("/settings")
async def change_settings(
    body: OrganizationSettings, session: ManageSettings, request: Request
) -> OrganizationSettings:
    return await _service(request).update(
        body, user_id=session.user_id, ip=client_ip(request), now=datetime.now(UTC)
    )
