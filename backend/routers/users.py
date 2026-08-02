"""User management router implementing docs/api-contracts-users.md."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from backend.admin.deps import require_permission
from backend.admin.errors import (
    UserInvalidRole,
    UserInvalidStatus,
    UserNotFound,
    UserSelfDisableForbidden,
)
from backend.admin.security import hash_password
from backend.admin.session_store import SessionStore, get_session_store
from backend.admin.user_payload import build_user_summary
from backend.repositories.role_store import RoleStore, get_role_store
from backend.repositories.user_store import UserRecord, UserStore, get_user_store
from backend.schemas.user import (
    CreateUserRequest,
    CreateUserResponse,
    UpdateStatusRequest,
    UpdateStatusResponse,
    UserListResponse,
)

router = APIRouter(prefix="/users", tags=["users"])

VALID_STATUSES = {"active", "disabled"}


@router.get("", response_model=UserListResponse)
def list_users(
    _user: UserRecord = Depends(require_permission("users:read")),
    users: UserStore = Depends(get_user_store),
    roles: RoleStore = Depends(get_role_store),
) -> UserListResponse:
    items = [build_user_summary(record, roles) for record in users.list_users()]
    return UserListResponse(items=items)


@router.post(
    "",
    response_model=CreateUserResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    payload: CreateUserRequest,
    _user: UserRecord = Depends(require_permission("users:write")),
    users: UserStore = Depends(get_user_store),
    roles: RoleStore = Depends(get_role_store),
) -> CreateUserResponse:
    role_id = payload.role_id
    if role_id is not None and roles.get_by_id(role_id) is None:
        raise UserInvalidRole()

    record = users.create_user(
        account=payload.account,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        role_id=role_id,
        status="active",
    )
    return CreateUserResponse(user=build_user_summary(record, roles))


@router.patch("/{user_id}/status", response_model=UpdateStatusResponse)
def update_user_status(
    user_id: str,
    payload: UpdateStatusRequest,
    caller: UserRecord = Depends(require_permission("users:write")),
    users: UserStore = Depends(get_user_store),
    roles: RoleStore = Depends(get_role_store),
    sessions: SessionStore = Depends(get_session_store),
) -> UpdateStatusResponse:
    if payload.status not in VALID_STATUSES:
        raise UserInvalidStatus()

    if user_id == caller.id and payload.status == "disabled":
        raise UserSelfDisableForbidden()

    record = users.get_by_id(user_id)
    if record is None:
        raise UserNotFound()

    updated = users.update_status(user_id, payload.status)
    if updated is None:
        raise UserNotFound()

    if payload.status == "disabled":
        sessions.delete_by_user_id(user_id)

    return UpdateStatusResponse(user=build_user_summary(updated, roles))
