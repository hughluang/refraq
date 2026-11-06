"""Single Entity MCP tool catalog: name, required Permission, description."""

from __future__ import annotations

from dataclasses import dataclass

from backend.admin.permissions import permissions_include
from backend.entity.mcp.guidance import TOOL_DESCRIPTIONS

MCP_PUBLIC_PATH = "/mcp/entity"
TOOLS_LIST_TTL_MS = 30_000


@dataclass(frozen=True, slots=True)
class McpToolSpec:
    name: str
    permission: str
    description: str


MCP_TOOLS: tuple[McpToolSpec, ...] = (
    McpToolSpec(
        "list_entities",
        "entity:data_read",
        TOOL_DESCRIPTIONS["list_entities"],
    ),
    McpToolSpec(
        "describe_entity",
        "entity:data_read",
        TOOL_DESCRIPTIONS["describe_entity"],
    ),
    McpToolSpec(
        "list_dictionary_codes",
        "entity:data_read",
        TOOL_DESCRIPTIONS["list_dictionary_codes"],
    ),
    McpToolSpec(
        "validate_sql",
        "entity:data_read",
        TOOL_DESCRIPTIONS["validate_sql"],
    ),
)


def tools_for_permissions(permissions: list[str]) -> list[McpToolSpec]:
    """Stable catalog order; only tools the permission set can call."""
    return [
        spec for spec in MCP_TOOLS if permissions_include(permissions, spec.permission)
    ]
