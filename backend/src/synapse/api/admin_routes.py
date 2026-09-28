"""Administration endpoints under ``/api/admin`` (ADR 0006, ADR 0007).

Each endpoint requires a role permission; every change is written to the audit log in the same
transaction (ADR 0008).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Request, status
from psycopg import AsyncConnection
from pydantic import BaseModel, Field

from synapse.api.deps import ApiError, client_ip, require
from synapse.authz import public as authz
from synapse.identity.public import (
    Account,
    AccountExistsError,
    AccountService,
    CurrentSession,
    IdentityService,
    LastAdministratorError,
    NewAccount,
    PasswordPolicyError,
    Role,
)
from synapse.kernel.database import Database

router = APIRouter(prefix="/api/admin", tags=["admin"])

ManageUsers = Annotated[CurrentSession, require("users.manage")]
ManageGroups = Annotated[CurrentSession, require("groups.manage")]
CreateCollections = Annotated[CurrentSession, require("collections.create")]
ManagePermissions = Annotated[CurrentSession, require("permissions.manage")]


def _accounts(request: Request) -> AccountService:
    service: AccountService = request.app.state.accounts
    return service


def _identity(request: Request) -> IdentityService:
    service: IdentityService = request.app.state.identity
    return service


@asynccontextmanager
async def _changes(
    request: Request, session: CurrentSession
) -> AsyncIterator[tuple[AsyncConnection, authz.Actor]]:
    """A tenant transaction and the actor for audited changes; maps errors to HTTP codes."""
    database: Database = request.app.state.database
    tenant_id: UUID = request.app.state.tenant_id
    actor = authz.Actor(
        tenant_id=tenant_id,
        user_id=session.user_id,
        role=session.role,
        ip=client_ip(request),
        now=datetime.now(UTC),
    )
    try:
        async with database.tenant_transaction(tenant_id) as connection:
            yield connection, actor
    except authz.NotFoundError as error:
        raise ApiError(status.HTTP_404_NOT_FOUND, "not_found") from error
    except authz.ConflictError as error:
        raise ApiError(status.HTTP_409_CONFLICT, "conflict") from error


# Users


class AccountView(BaseModel):
    id: UUID
    email: str
    display_name: str
    role: Role
    status: Literal["active", "disabled"]
    locale: str
    has_mfa: bool


def _account_view(account: Account) -> AccountView:
    return AccountView(
        id=account.id,
        email=account.email,
        display_name=account.display_name,
        role=account.role,
        status=account.status,
        locale=account.locale,
        has_mfa=account.has_mfa,
    )


class NewAccountRequest(BaseModel):
    email: str = Field(max_length=254)
    display_name: str = Field(min_length=1, max_length=200)
    role: Role
    locale: Literal["tr", "en"] = "tr"
    password: str = Field(max_length=1024)


class AccountChange(BaseModel):
    role: Role | None = None
    status: Literal["active", "disabled"] | None = None


@router.get("/users")
async def list_users(_: ManageUsers, request: Request) -> list[AccountView]:
    return [_account_view(account) for account in await _accounts(request).list_accounts()]


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: NewAccountRequest, session: ManageUsers, request: Request
) -> dict[str, UUID]:
    try:
        user_id = await _identity(request).create_user(
            NewAccount(
                email=body.email,
                display_name=body.display_name,
                role=body.role,
                password=body.password,
                locale=body.locale,
            ),
            actor_user_id=session.user_id,
        )
    except PasswordPolicyError as error:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_CONTENT, error.code) from error
    except AccountExistsError as error:
        raise ApiError(status.HTTP_409_CONFLICT, "email_taken") from error
    return {"id": user_id}


@router.patch("/users/{user_id}")
async def change_user(
    user_id: UUID, body: AccountChange, session: ManageUsers, request: Request
) -> AccountView:
    try:
        account = await _accounts(request).update_account(
            user_id, actor_user_id=session.user_id, role=body.role, status=body.status
        )
    except LastAdministratorError as error:
        raise ApiError(status.HTTP_409_CONFLICT, "last_administrator") from error
    if account is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "not_found")
    return _account_view(account)


# Groups


class GroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class MemberRequest(BaseModel):
    user_id: UUID


@router.get("/groups")
async def list_groups(session: ManageGroups, request: Request) -> list[authz.Group]:
    async with _changes(request, session) as (connection, _):
        return await authz.management.list_groups(connection)


@router.post("/groups", status_code=status.HTTP_201_CREATED)
async def create_group(
    body: GroupRequest, session: ManageGroups, request: Request
) -> dict[str, UUID]:
    async with _changes(request, session) as (connection, actor):
        return {"id": await authz.management.create_group(connection, actor, body.name)}


@router.get("/groups/{group_id}/members")
async def list_members(
    group_id: UUID, session: ManageGroups, request: Request
) -> list[authz.Member]:
    async with _changes(request, session) as (connection, _):
        return await authz.management.list_members(connection, group_id)


@router.post("/groups/{group_id}/members", status_code=status.HTTP_204_NO_CONTENT)
async def add_member(
    group_id: UUID, body: MemberRequest, session: ManageGroups, request: Request
) -> None:
    async with _changes(request, session) as (connection, actor):
        await authz.management.add_member(connection, actor, group_id, body.user_id)


@router.delete("/groups/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    group_id: UUID, user_id: UUID, session: ManageGroups, request: Request
) -> None:
    async with _changes(request, session) as (connection, actor):
        await authz.management.remove_member(connection, actor, group_id, user_id)


# Collections and grants


class CollectionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_id: UUID | None = None


class GrantRequest(BaseModel):
    principal_type: authz.PrincipalType
    principal: str = Field(min_length=1, max_length=64)
    permission: authz.DocumentPermission


@router.get("/collections")
async def list_collections(session: CreateCollections, request: Request) -> list[authz.Collection]:
    async with _changes(request, session) as (connection, _):
        return await authz.management.list_collections(connection)


@router.post("/collections", status_code=status.HTTP_201_CREATED)
async def create_collection(
    body: CollectionRequest, session: CreateCollections, request: Request
) -> dict[str, UUID]:
    async with _changes(request, session) as (connection, actor):
        collection_id = await authz.management.create_collection(
            connection, actor, body.name, body.parent_id
        )
    return {"id": collection_id}


@router.get("/collections/{collection_id}/grants")
async def list_grants(
    collection_id: UUID, session: ManagePermissions, request: Request
) -> list[authz.Grant]:
    async with _changes(request, session) as (connection, _):
        return await authz.management.list_grants(connection, collection_id)


@router.post("/collections/{collection_id}/grants", status_code=status.HTTP_201_CREATED)
async def add_grant(
    collection_id: UUID, body: GrantRequest, session: ManagePermissions, request: Request
) -> dict[str, UUID]:
    async with _changes(request, session) as (connection, actor):
        grant_id = await authz.management.add_grant(
            connection, actor, collection_id, body.principal_type, body.principal, body.permission
        )
    return {"id": grant_id}


@router.delete("/grants/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_grant(grant_id: UUID, session: ManagePermissions, request: Request) -> None:
    async with _changes(request, session) as (connection, actor):
        await authz.management.remove_grant(connection, actor, grant_id)
