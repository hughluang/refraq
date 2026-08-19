"""Role and permission catalog router implementing docs/api-contracts-roles.md."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from backend.core.pagination import PageParams, page_params

from backend.admin import roles as role_domain
from backend.admin.deps import require_permission
from backend.admin.errors import RoleInUse, RoleNotFound
from backend.admin.permissions import ALL_PERMISSIONS, PERMISSION_DESCRIPTIONS
from backend.admin.roles import effective_permissions
from backend.admin.role_store import RoleRecord, RoleStore, get_role_store
from backend.admin.user_store import UserRecord, UserStore, get_user_store
from backend.admin.schemas.role import (
    CreateRoleRequest,
    PermissionCatalogEntry,
    PermissionCatalogResponse,
    RoleListResponse,
    RoleResponse,
    RoleSummary,
    UpdateRoleRequest,
)

router = APIRouter(tags=["roles"])


def _to_summary(
    record: RoleRecord, users: UserStore
) -> RoleSummary:
    return RoleSummary(
        id=record.id,
        key=record.key,
        name=record.name,
        permissions=effective_permissions(record),
        locked=record.locked,
        user_count=users.count_by_role_id(record.id),
    )


@router.get("/permissions", response_model=PermissionCatalogResponse)
def list_permissions(
    _user: UserRecord = Depends(require_permission("roles:read")),
) -> PermissionCatalogResponse:
    items = [
        PermissionCatalogEntry(key=key, description=PERMISSION_DESCRIPTIONS[key])
        for key in ALL_PERMISSIONS
    ]
    return PermissionCatalogResponse(items=items)


@router.get("/roles", response_model=RoleListResponse)
def list_roles(
    _user: UserRecord = Depends(require_permission("roles:read")),
    roles: RoleStore = Depends(get_role_store),
    users: UserStore = Depends(get_user_store),
    page: PageParams = Depends(page_params(default_limit=50, max_limit=200)),
) -> RoleListResponse:
    records, total = roles.list_roles(limit=page.limit, offset=page.offset)
    return RoleListResponse(
        items=[_to_summary(record, users) for record in records],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/roles",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_role(
    payload: CreateRoleRequest,
    _user: UserRecord = Depends(require_permission("roles:write")),
    roles: RoleStore = Depends(get_role_store),
    users: UserStore = Depends(get_user_store),
) -> RoleResponse:
    record = role_domain.create_role(
        roles,
        key=payload.key,
        name=payload.name,
        permissions=payload.permissions,
    )
    return RoleResponse(role=_to_summary(record, users))


@router.get("/roles/{role_id}", response_model=RoleResponse)
def get_role(
    role_id: str,
    _user: UserRecord = Depends(require_permission("roles:read")),
    roles: RoleStore = Depends(get_role_store),
    users: UserStore = Depends(get_user_store),
) -> RoleResponse:
    record = roles.get_by_id(role_id)
    if record is None:
        raise RoleNotFound()
    return RoleResponse(role=_to_summary(record, users))


@router.patch("/roles/{role_id}", response_model=RoleResponse)
def update_role(
    role_id: str,
    payload: UpdateRoleRequest,
    _user: UserRecord = Depends(require_permission("roles:write")),
    roles: RoleStore = Depends(get_role_store),
    users: UserStore = Depends(get_user_store),
) -> RoleResponse:
    record = role_domain.update_role(
        roles,
        role_id,
        name=payload.name,
        permissions=payload.permissions,
    )
    if record is None:
        raise RoleNotFound()
    return RoleResponse(role=_to_summary(record, users))


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(
    role_id: str,
    _user: UserRecord = Depends(require_permission("roles:write")),
    roles: RoleStore = Depends(get_role_store),
    users: UserStore = Depends(get_user_store),
) -> Response:
    record = roles.get_by_id(role_id)
    if record is None:
        raise RoleNotFound()
    # Prefer RoleLocked (domain) over RoleInUse when a locked role still has users.
    if not record.locked and users.count_by_role_id(role_id) > 0:
        raise RoleInUse()
    role_domain.delete_role(roles, role_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
