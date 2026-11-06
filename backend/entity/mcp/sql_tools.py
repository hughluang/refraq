"""validate_sql. Importing this module registers the tool on the host."""

from __future__ import annotations

import json

from mcp.types import ToolAnnotations

from backend.entity.mcp.actor import current_actor
from backend.entity.mcp.guidance import TOOL_DESCRIPTIONS
from backend.entity.mcp.server import _err, _require, mcp
from backend.entity.mcp.sql_prepare import prepare_entity_sql


@mcp.tool(
    description=TOOL_DESCRIPTIONS["validate_sql"],
    annotations=ToolAnnotations(read_only_hint=True),
)
def validate_sql(sql: str) -> str:
    """Check one read-only statement. No entity connection and no access log."""
    try:
        user, _token_id = current_actor()
        _require(user, "entity:data_read")
        prepared = prepare_entity_sql(sql, user)
        return json.dumps(
            {
                "entities": list(prepared.entities),
                "partial_columns": [
                    {"table_name": item.table_name, "column": item.column}
                    for item in prepared.partial_columns
                ],
            }
        )
    except Exception as exc:  # noqa: BLE001 — tool failures stay in the envelope
        return _err(exc)
