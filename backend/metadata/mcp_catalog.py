"""Single MCP tool catalog: name, required Permission, description, execution class."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from backend.admin.permissions import permissions_include
from backend.metadata.mcp_guidance import TOOL_DESCRIPTIONS

MCP_PUBLIC_PATH = "/mcp"
TOOLS_LIST_TTL_MS = 30_000

Execution = Literal["read", "write"]


@dataclass(frozen=True, slots=True)
class McpToolSpec:
    name: str
    permission: str
    description: str
    execution: Execution


def _tool(name: str, permission: str, execution: Execution) -> McpToolSpec:
    return McpToolSpec(name, permission, TOOL_DESCRIPTIONS[name], execution)


MCP_TOOLS: tuple[McpToolSpec, ...] = (
    _tool("search_sources", "sources:read", "read"),
    _tool("get_source", "sources:read", "read"),
    _tool("list_objects", "metadata:read", "read"),
    _tool("get_object", "metadata:read", "read"),
    _tool("get_object_semantics", "metadata:read", "read"),
    _tool("get_object_columns", "metadata:read", "read"),
    _tool("get_object_ddl", "metadata:read", "read"),
    _tool("set_object_semantics", "metadata:write", "write"),
    _tool("set_column_semantics", "metadata:write", "write"),
    _tool("list_semantics_changes", "metadata:read", "read"),
    _tool("search_objects", "metadata:read", "read"),
    _tool("search_columns", "metadata:read", "read"),
    _tool("list_joins", "metadata:read", "read"),
    _tool("upsert_join", "metadata:write", "write"),
    _tool("patch_join", "metadata:write", "write"),
    _tool("reject_join", "metadata:write", "write"),
    _tool("restore_join", "metadata:write", "write"),
    _tool("upsert_joins", "metadata:write", "write"),
    _tool("delete_join", "metadata:write", "write"),
    _tool("find_join_path", "metadata:read", "read"),
    _tool("run_sql", "query:run", "read"),
)


def tools_for_permissions(permissions: list[str]) -> list[McpToolSpec]:
    """Stable catalog order; only tools the permission set can call."""
    return [spec for spec in MCP_TOOLS if permissions_include(permissions, spec.permission)]
