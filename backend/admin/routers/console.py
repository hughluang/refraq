"""Console navigation and module-identity router."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.admin.console_modules import build_module_identities, build_navigation
from backend.admin.deps import require_permission, resolve_user_permissions
from backend.admin.role_store import RoleStore, get_role_store
from backend.admin.user_store import UserRecord
from backend.admin.schemas.console import (
    ModuleActionsResponse,
    ModuleIdentitiesResponse,
    ModuleIdentityResponse,
    ModuleRoutesResponse,
    NavigationGroupResponse,
    NavigationModuleResponse,
    NavigationResponse,
)

router = APIRouter(prefix="/console", tags=["console"])


@router.get("/navigation", response_model=NavigationResponse)
def get_navigation(
    user: UserRecord = Depends(require_permission("console:access")),
    roles: RoleStore = Depends(get_role_store),
) -> NavigationResponse:
    permissions = resolve_user_permissions(user, roles)
    groups = build_navigation(permissions)
    return NavigationResponse(
        groups=[
            NavigationGroupResponse(
                id=group.id,
                label_key=group.label_key,
                modules=[
                    NavigationModuleResponse(
                        id=module.id,
                        label_key=module.label_key,
                        route=module.route,
                    )
                    for module in group.modules
                ],
            )
            for group in groups
        ]
    )


@router.get("/module-identities", response_model=ModuleIdentitiesResponse)
def get_module_identities(
    _user: UserRecord = Depends(require_permission("console:access")),
) -> ModuleIdentitiesResponse:
    identities = build_module_identities()
    return ModuleIdentitiesResponse(
        modules=[
            ModuleIdentityResponse(
                id=module.id,
                label_key=module.label_key,
                routes=ModuleRoutesResponse(
                    list=module.routes.list,
                    create=module.routes.create,
                    edit=module.routes.edit,
                    show=module.routes.show,
                ),
                actions=ModuleActionsResponse(
                    list=module.actions.list,
                    create=module.actions.create,
                    edit=module.actions.edit,
                    delete=module.actions.delete,
                    show=module.actions.show,
                ),
            )
            for module in identities
        ]
    )
