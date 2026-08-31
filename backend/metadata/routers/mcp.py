"""Current-user MCP catalog (Account Center). Same crop as tools/list."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.admin.deps import get_current_user, resolve_user_permissions
from backend.admin.role_store import RoleStore, get_role_store
from backend.admin.user_store import UserRecord
from backend.metadata.mcp_catalog import MCP_PUBLIC_PATH, tools_for_permissions
from backend.metadata.schemas.mcp import McpCatalogResponse

router = APIRouter(tags=["mcp"])


@router.get("/mcp/catalog", response_model=McpCatalogResponse)
def get_mcp_catalog(
    user: UserRecord = Depends(get_current_user),
    roles: RoleStore = Depends(get_role_store),
) -> McpCatalogResponse:
    perms = resolve_user_permissions(user, roles)
    return McpCatalogResponse(
        public_path=MCP_PUBLIC_PATH,
        tools=tools_for_permissions(perms),
    )
