"""validate_sql and run_sql. Importing this module registers the tools."""

from __future__ import annotations

import json
from typing import Any

from mcp.types import ToolAnnotations

from backend.admin.principal import require_current_principal
from backend.core.request_id import get_request_id
from backend.entity.mcp.guidance import TOOL_DESCRIPTIONS
from backend.entity.mcp.server import _err, mcp
from backend.entity.mcp.sql_prepare import prepare_entity_sql
from backend.entity.mcp.sql_run import run_entity_sql


@mcp.tool(
    description=TOOL_DESCRIPTIONS["validate_sql"],
    annotations=ToolAnnotations(read_only_hint=True),
)
def validate_sql(sql: str) -> str:
    """Check one read-only statement. No entity connection and no access log."""
    try:
        principal = require_current_principal()
        principal.require("entity:data_read")
        prepared = prepare_entity_sql(sql, principal.user)
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


@mcp.tool(
    description=TOOL_DESCRIPTIONS["run_sql"],
    annotations=ToolAnnotations(read_only_hint=True),
)
async def run_sql(sql: str, max_rows: int | None = None) -> str:
    """Execute one prepared statement. The result echoes the submitted SQL."""
    try:
        principal = require_current_principal()
        principal.require("entity:data_read")
        request_id = get_request_id()

        presented = await principal.admit(
            lambda: run_entity_sql(
                sql,
                principal.user,
                pat_id=principal.actor_token_id,
                request_id=request_id,
                max_rows=max_rows,
            )
        )
        return json.dumps(presented)
    except Exception as exc:  # noqa: BLE001 — tool failures stay in the envelope
        return _err(exc)
