"""User management router implementing docs/api-contracts-users.md."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status

from backend.core.pagination import PageParams, page_params

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.lifecycle import disable_user, enable_user
from backend.admin.oauth.runtime_store import (
    OAuthRuntimeStore,
    get_oauth_runtime_store,
)
from backend.admin.errors import (
    AccountInvalidLocale,
    UserInvalidRole,
    UserInvalidStatus,
    UserLastLocalSuperAdmin,
    UserNotFound,
    UserSelfDisableForbidden,
    UserSystemImmutable,
)
from backend.admin.locales import DEFAULT_LOCALE, is_supported_locale
from backend.admin.security import hash_password
from backend.admin.user_payload import build_user_summary
from backend.admin.role_store import RoleStore, get_role_store
from backend.admin.roles import is_last_local_active_super_admin
from backend.admin.session_store import SessionStore, get_session_store
from backend.admin.user_store import IdentitySource, UserRecord, UserStore, get_user_store
from backend.admin.schemas.user import (
    CreateUserRequest,
    CreateUserResponse,
    GetUserResponse,
    UpdateRoleRequest,
    UpdateRoleResponse,
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
    page: PageParams = Depends(page_params(default_limit=50, max_limit=200)),
    include_system: bool = Query(default=False),
    q: str | None = Query(default=None),
    identity_source: IdentitySource | None = Query(default=None),
) -> UserListResponse:
    records, total = users.list_users(
        limit=page.limit,
        offset=page.offset,
        include_system=include_system,
        q=(q or "").strip() or None,
        identity_source=identity_source,
    )
    return UserListResponse(
        items=[build_user_summary(record, roles) for record in records],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


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

    locale = payload.locale or DEFAULT_LOCALE
    if not is_supported_locale(locale):
        raise AccountInvalidLocale()

    email = payload.email.strip() if payload.email else None
    if email == "":
        email = None

    record = users.create_user(
        account=payload.account,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        role_id=role_id,
        status="active",
        email=email,
        locale=locale,
    )
    return CreateUserResponse(user=build_user_summary(record, roles))


@router.get("/{user_id}", response_model=GetUserResponse)
def get_user(
    user_id: str,
    _user: UserRecord = Depends(require_permission("users:read")),
    users: UserStore = Depends(get_user_store),
    roles: RoleStore = Depends(get_role_store),
) -> GetUserResponse:
    record = users.get_by_id(user_id)
    if record is None:
        raise UserNotFound()
    return GetUserResponse(user=build_user_summary(record, roles))


@router.patch("/{user_id}/status", response_model=UpdateStatusResponse)
def update_user_status(
    user_id: str,
    payload: UpdateStatusRequest,
    request: Request,
    caller: UserRecord = Depends(require_permission("users:write")),
    users: UserStore = Depends(get_user_store),
    roles: RoleStore = Depends(get_role_store),
    sessions: SessionStore = Depends(get_session_store),
    oauth_runtime: OAuthRuntimeStore = Depends(get_oauth_runtime_store),
) -> UpdateStatusResponse:
    if payload.status not in VALID_STATUSES:
        raise UserInvalidStatus()

    if payload.status == "disabled":
        updated = disable_user(
            user_id=user_id,
            users=users,
            roles=roles,
            sessions=sessions,
            oauth_runtime=oauth_runtime,
            caller_user_id=caller.id,
            actor_token_id=get_actor_token_id(request),
            enforce_last_super_admin=False,
        )
    else:
        updated = enable_user(
            user_id=user_id,
            users=users,
            caller_user_id=caller.id,
            actor_token_id=get_actor_token_id(request),
        )

    return UpdateStatusResponse(user=build_user_summary(updated, roles))


@router.patch("/{user_id}/role", response_model=UpdateRoleResponse)
def update_user_role(
    user_id: str,
    payload: UpdateRoleRequest,
    _caller: UserRecord = Depends(require_permission("users:write")),
    users: UserStore = Depends(get_user_store),
    roles: RoleStore = Depends(get_role_store),
) -> UpdateRoleResponse:
    record = users.get_by_id(user_id)
    if record is None:
        raise UserNotFound()
    if record.identity_source == "system":
        raise UserSystemImmutable()

    role_id = payload.role_id
    if role_id is not None and roles.get_by_id(role_id) is None:
        raise UserInvalidRole()
    if role_id != record.role_id and is_last_local_active_super_admin(
        record, users, roles
    ):
        raise UserLastLocalSuperAdmin()

    updated = users.update_role(user_id, role_id)
    if updated is None:
        raise UserNotFound()
    return UpdateRoleResponse(user=build_user_summary(updated, roles))
