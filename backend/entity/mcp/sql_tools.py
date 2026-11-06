"""validate_sql and run_sql. Importing this module registers the tools."""

from __future__ import annotations

import json
from typing import Any

from mcp.types import ToolAnnotations

from backend.core.admission import await_admitted
from backend.core.request_id import bind_request_id, get_request_id
from backend.entity.access.actor_token import actor_token
from backend.entity.mcp.actor import current_actor
from backend.entity.mcp.guidance import TOOL_DESCRIPTIONS
from backend.entity.mcp.server import _err, _require, mcp
from backend.entity.mcp.sql_prepare import prepare_entity_sql
from backend.entity.mcp.sql_run import run_entity_sql


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


@mcp.tool(
    description=TOOL_DESCRIPTIONS["run_sql"],
    annotations=ToolAnnotations(read_only_hint=True),
)
async def run_sql(sql: str, max_rows: int | None = None) -> str:
    """Execute one prepared statement. The result echoes the submitted SQL."""
    try:
        user, token_id = current_actor()
        _require(user, "entity:data_read")
        request_id = get_request_id()

        def _run() -> dict[str, Any]:
            with actor_token(token_id), bind_request_id(request_id):
                return run_entity_sql(
                    sql,
                    user,
                    pat_id=token_id,
                    request_id=request_id,
                    max_rows=max_rows,
                )

        presented = await await_admitted(user.id, _run)
        return json.dumps(presented)
    except Exception as exc:  # noqa: BLE001 — tool failures stay in the envelope
        return _err(exc)
