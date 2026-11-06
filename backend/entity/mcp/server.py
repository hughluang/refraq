"""Entity MCP tools. Failures return the tool-error envelope and do not raise."""

from __future__ import annotations

import json
from typing import Any

from mcp.server import CacheHint, MCPServer
from mcp.types import Tool as MCPTool
from mcp.types import ToolAnnotations
from pydantic.json_schema import SkipJsonSchema

from backend.admin.deps import resolve_user_permissions
from backend.admin.errors import AuthForbidden
from backend.admin.permissions import permissions_include
from backend.admin.role_store import get_role_store
from backend.admin.user_store import UserRecord
from backend.core.errors import AppError
from backend.core.pagination import ENTITY_LIST
from backend.entity.access.membership import person_of, readable_entity_ids
from backend.entity.errors import EntityRequestInvalid
from backend.entity.mcp.actor import current_actor
from backend.entity.mcp.describe import describe_for, dictionary_codes
from backend.entity.mcp.catalog import TOOLS_LIST_TTL_MS, tools_for_permissions
from backend.entity.mcp.guidance import SERVER_INSTRUCTIONS, TOOL_DESCRIPTIONS
from backend.entity.records import BusinessEntityRecord
from backend.entity.store import get_entity_store
from backend.tags.api import KIND_ENTITY, read_assignment


class RefraqEntityMcp(MCPServer):
    """Entity MCP host: tools/list is cropped to the current PAT's Role."""

    async def list_tools(self) -> list[MCPTool]:
        tools = {tool.name: tool for tool in await super().list_tools()}
        user, _token_id = current_actor()
        perms = resolve_user_permissions(user, get_role_store())
        return [tools[spec.name] for spec in tools_for_permissions(perms)]


mcp = RefraqEntityMcp(
    "refraq-entity",
    instructions=SERVER_INSTRUCTIONS,
    cache_hints={
        "tools/list": CacheHint(ttl_ms=TOOLS_LIST_TTL_MS, scope="private"),
        "prompts/list": CacheHint(ttl_ms=TOOLS_LIST_TTL_MS, scope="private"),
    },
)


def _require(user: UserRecord, permission: str) -> None:
    perms = resolve_user_permissions(user, get_role_store())
    if not permissions_include(perms, permission):
        raise AuthForbidden(f"Missing permission {permission}")


def _err(exc: Exception) -> str:
    """Tool-error envelope `{ "error": { "code", "message" } }`. Tools return it."""
    if isinstance(exc, AppError):
        payload: dict[str, str] = {"code": exc.code, "message": exc.message}
    else:
        payload = {"code": "MCP_ERROR", "message": str(exc)}
    return json.dumps({"error": payload})


def _entity_item(entity: BusinessEntityRecord) -> dict[str, Any]:
    assignment = read_assignment(KIND_ENTITY, entity.id)
    return {
        "table_name": entity.table_name,
        "name": entity.name,
        "description": entity.description,
        "tags": [{"id": tag.id, "name": tag.name} for tag in assignment.tags],
    }


@mcp.tool(
    description=TOOL_DESCRIPTIONS["list_entities"],
    annotations=ToolAnnotations(read_only_hint=True),
)
def list_entities(
    query_text: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> str:
    """Page serving Entities the caller can read."""
    try:
        user, _token_id = current_actor()
        _require(user, "entity:data_read")
        lim = ENTITY_LIST.clamp(limit)
        off = max(0, int(offset or 0))
        candidates = get_entity_store().list_entity_candidates(
            q=query_text,
            statuses=frozenset({"serving"}),
            subject_ids=None,
            match_description=True,
        )
        if candidates:
            visible = readable_entity_ids(
                [entity.id for entity in candidates], person_of(user)
            )
            candidates = [entity for entity in candidates if entity.id in visible]
        candidates.sort(key=lambda entity: entity.table_name)
        page = candidates[off : off + lim]
        return json.dumps(
            {
                "items": [_entity_item(entity) for entity in page],
                "total": len(candidates),
                "limit": lim,
                "offset": off,
            }
        )
    except Exception as exc:  # noqa: BLE001 — tool failures stay in the envelope
        return _err(exc)


def _reject_narrow(narrow: Any) -> None:
    if narrow is not None:
        raise EntityRequestInvalid("narrow is not accepted")


@mcp.tool(
    description=TOOL_DESCRIPTIONS["describe_entity"],
    annotations=ToolAnnotations(read_only_hint=True),
)
def describe_entity(
    table_name: str,
    narrow: SkipJsonSchema[Any] = None,
) -> str:
    """Describe one Entity as the caller can read it."""
    try:
        user, _token_id = current_actor()
        _require(user, "entity:data_read")
        _reject_narrow(narrow)
        return json.dumps(describe_for(user, table_name))
    except Exception as exc:  # noqa: BLE001 — tool failures stay in the envelope
        return _err(exc)


@mcp.tool(
    description=TOOL_DESCRIPTIONS["list_dictionary_codes"],
    annotations=ToolAnnotations(read_only_hint=True),
)
def list_dictionary_codes(
    table_name: str,
    attribute: str,
    query_text: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    narrow: SkipJsonSchema[Any] = None,
) -> str:
    """Page codes of one dictionary attribute in the caller's read shape."""
    try:
        user, _token_id = current_actor()
        _require(user, "entity:data_read")
        _reject_narrow(narrow)
        return json.dumps(
            dictionary_codes(
                user,
                table_name,
                attribute,
                query_text=query_text,
                limit=limit,
                offset=offset,
            )
        )
    except Exception as exc:  # noqa: BLE001 — tool failures stay in the envelope
        return _err(exc)


import backend.entity.mcp.sql_tools as _entity_sql_tools  # noqa: E402,F401
