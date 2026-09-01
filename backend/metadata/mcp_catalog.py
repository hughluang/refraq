"""Single MCP tool catalog: name, required Permission, description."""

from __future__ import annotations

from dataclasses import dataclass

from backend.admin.permissions import permissions_include

MCP_PUBLIC_PATH = "/mcp"
TOOLS_LIST_TTL_MS = 30_000


@dataclass(frozen=True, slots=True)
class McpToolSpec:
    name: str
    permission: str
    description: str


MCP_TOOLS: tuple[McpToolSpec, ...] = (
    McpToolSpec(
        "search_sources",
        "sources:read",
        "Search/list Sources (sources:read).",
    ),
    McpToolSpec(
        "get_source",
        "sources:read",
        "Get Source detail by locator (sources:read).",
    ),
    McpToolSpec(
        "list_objects",
        "metadata:read",
        "List Catalog Objects under a Source locator (metadata:read).",
    ),
    McpToolSpec(
        "get_object",
        "metadata:read",
        "Get Catalog Object with columns, DDL, and object semantics by locator (metadata:read).",
    ),
    McpToolSpec(
        "set_object_semantics",
        "metadata:write",
        "Incremental object semantics write (metadata:write, semantic_source=mcp).",
    ),
    McpToolSpec(
        "set_column_semantics",
        "metadata:write",
        "Batch column semantics under one object locator (metadata:write).",
    ),
    McpToolSpec(
        "list_business_domains",
        "metadata:read",
        "List Business Domains (metadata:read).",
    ),
    McpToolSpec(
        "create_business_domain",
        "metadata:write",
        "Create a Business Domain (metadata:write).",
    ),
    McpToolSpec(
        "search_objects",
        "metadata:read",
        "Cross-Source object search (metadata:read).",
    ),
    McpToolSpec(
        "search_columns",
        "metadata:read",
        "Cross-Source column search (metadata:read).",
    ),
    McpToolSpec(
        "list_joins",
        "metadata:read",
        "List joins for an object locator (metadata:read).",
    ),
    McpToolSpec(
        "upsert_join",
        "metadata:write",
        "Create a join edge (metadata:write, Join Change attester mcp). Duplicate pairs are refused.",
    ),
    McpToolSpec(
        "patch_join",
        "metadata:write",
        "Amend a join edge (metadata:write). Does not change first attester.",
    ),
    McpToolSpec(
        "reject_join",
        "metadata:write",
        "Reject a join pair (metadata:write). Blocks every writer until restore.",
    ),
    McpToolSpec(
        "restore_join",
        "metadata:write",
        "Lift Join Rejection (metadata:write).",
    ),
    McpToolSpec(
        "upsert_joins",
        "metadata:write",
        "Batch upsert joins; all same Source (metadata:write, Join Change attester mcp).",
    ),
    McpToolSpec(
        "delete_join",
        "metadata:write",
        "Remove a human-created, non-rejected edge by id (metadata:write).",
    ),
    McpToolSpec(
        "find_join_path",
        "metadata:read",
        "Join path lookup from start locator (metadata:read).",
    ),
    McpToolSpec(
        "run_sql",
        "query:run",
        "Run a single read-only SELECT against a Source (query:run).",
    ),
)


def tools_for_permissions(permissions: list[str]) -> list[McpToolSpec]:
    """Stable catalog order; only tools the permission set can call."""
    return [spec for spec in MCP_TOOLS if permissions_include(permissions, spec.permission)]
