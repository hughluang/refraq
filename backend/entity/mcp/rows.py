"""get_row and query_rows. Importing this module registers the tools."""

from __future__ import annotations

import json
import warnings
from typing import Any

from mcp.types import ToolAnnotations
from pydantic.json_schema import PydanticJsonSchemaWarning, SkipJsonSchema

from backend.core.admission import await_admitted
from backend.core.request_id import bind_request_id, get_request_id
from backend.entity.access.actor_token import actor_token
from backend.entity.data import service as data_service
from backend.entity.mcp.actor import current_actor
from backend.entity.mcp.guidance import TOOL_DESCRIPTIONS
from backend.entity.mcp.server import _err, _reject_narrow, _require, mcp

# Omitted after_row_id keeps offset paging. JSON null is the first keyset page.
_OMITTED: Any = object()


def _get_body(row_id: Any, business_key: Any) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if row_id is not None:
        body["row_id"] = row_id
    if business_key is not None:
        body["business_key"] = business_key
    return body


def _query_body(
    *,
    filters: Any,
    fields: Any,
    limit: Any,
    offset: Any,
    include_total: Any,
    after_row_id: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if filters is not None:
        body["filters"] = filters
    if fields is not None:
        body["fields"] = fields
    if limit is not None:
        body["limit"] = limit
    if offset is not None:
        body["offset"] = offset
    if include_total is not None:
        body["include_total"] = include_total
    if after_row_id is not _OMITTED:
        body["after_row_id"] = after_row_id
    return body


@mcp.tool(
    description=TOOL_DESCRIPTIONS["get_row"],
    annotations=ToolAnnotations(read_only_hint=True),
)
async def get_row(
    table_name: str,
    row_id: int | None = None,
    business_key: Any = None,
    narrow: SkipJsonSchema[Any] = None,
) -> str:
    """One row, the same object Entity Data API get returns, wrapped as row."""
    try:
        user, token_id = current_actor()
        _require(user, "entity:data_read")
        _reject_narrow(narrow)
        body = _get_body(row_id, business_key)
        request_id = get_request_id()

        def _run() -> dict[str, Any]:
            with actor_token(token_id), bind_request_id(request_id):
                return data_service.get_row(table_name, body, user)

        row = await await_admitted(user.id, _run)
        return json.dumps({"row": row})
    except Exception as exc:  # noqa: BLE001 — tool failures stay in the envelope
        return _err(exc)


with warnings.catch_warnings():
    warnings.simplefilter("ignore", PydanticJsonSchemaWarning)

    @mcp.tool(
        description=TOOL_DESCRIPTIONS["query_rows"],
        annotations=ToolAnnotations(read_only_hint=True),
    )
    async def query_rows(
        table_name: str,
        filters: dict[str, Any] | None = None,
        fields: list[str] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        include_total: bool | None = None,
        after_row_id: int | None = _OMITTED,
        narrow: SkipJsonSchema[Any] = None,
    ) -> str:
        """Entity Data API query envelope, offset or keyset, limits not clamped."""
        try:
            user, token_id = current_actor()
            _require(user, "entity:data_read")
            _reject_narrow(narrow)
            body = _query_body(
                filters=filters,
                fields=fields,
                limit=limit,
                offset=offset,
                include_total=include_total,
                after_row_id=after_row_id,
            )
            request_id = get_request_id()

            def _run() -> dict[str, Any]:
                with actor_token(token_id), bind_request_id(request_id):
                    return data_service.query_rows(table_name, body, user)

            page = await await_admitted(user.id, _run)
            return json.dumps(page)
        except Exception as exc:  # noqa: BLE001 — tool failures stay in the envelope
            return _err(exc)
