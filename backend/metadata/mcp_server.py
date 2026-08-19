"""Metadata MCP tools — locator-first; same domain services/permissions as HTTP."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from backend.admin.deps import resolve_pat_bearer, resolve_user_permissions
from backend.admin.errors import AuthForbidden, AuthUnauthenticated
from backend.admin.permissions import permissions_include
from backend.admin.role_store import get_role_store
from backend.admin.user_store import UserRecord
from backend.core.errors import AppError
from backend.core.time import format_instant
from backend.jobs.errors import JobNotFound
from backend.jobs.store import get_job_store
from backend.metadata.business_domains import service as domain_service
from backend.metadata.catalog import join_writes as catalog_joins
from backend.metadata.catalog import refs as catalog_refs
from backend.metadata.catalog import semantics as catalog_semantics
from backend.metadata.catalog import service as catalog_reads
from backend.metadata.catalog import views as catalog_views
from backend.metadata.query import service as query_service
from backend.metadata.sources import service as source_service
from backend.metadata.sources.store import get_source_store


mcp = MCPServer("refraq-metadata")

def _actor_from_token(authorization: str | None) -> tuple[UserRecord, str]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthUnauthenticated()
    token = authorization.split(" ", 1)[1].strip()
    return resolve_pat_bearer(token)

def _mcp_strip_empty(data: dict[str, Any]) -> dict[str, Any]:
    """Drop null / blank / empty collections so MCP stays additive (no clear)."""
    out: dict[str, Any] = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict)) and len(value) == 0:
            continue
        out[key] = value
    return out

def _require(user: UserRecord, permission: str) -> None:
    roles = get_role_store()
    perms = resolve_user_permissions(user, roles)
    if not permissions_include(perms, permission):
        raise AuthForbidden(f"Missing permission {permission}")

def _err(exc: Exception) -> str:
    if isinstance(exc, AppError):
        payload: dict[str, str] = {"code": exc.code, "message": exc.message}
    else:
        payload = {"code": "MCP_ERROR", "message": str(exc)}
    return json.dumps({"error": payload})

def _json_default(obj: object) -> Any:
    if isinstance(obj, datetime):
        return format_instant(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

def _dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=_json_default)

def _clamp(value: int | None, *, default: int, maximum: int) -> int:
    if value is None:
        return default
    return max(1, min(maximum, int(value)))

def _object_payload(
    view: catalog_views.ObjectView, *, include_columns: bool
) -> dict[str, Any]:
    return catalog_views.object_view_as_dict(view, include_columns=include_columns)

def _join_payload_from_record(record: Any) -> dict[str, Any]:
    return catalog_views.join_view_as_dict(catalog_views.join_view(record))

@mcp.tool()
def search_sources(
    authorization: str,
    query_text: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> str:
    """Search/list Sources (sources:read)."""
    try:
        user, _token_id = _actor_from_token(authorization)
        _require(user, "sources:read")
        items, _ = get_source_store().list_sources()
        if query_text:
            ql = query_text.lower()
            items = [
                s
                for s in items
                if ql in s.key.lower()
                or ql in s.name.lower()
                or ql in (s.locator_key or "").lower()
            ]
        total = len(items)
        lim = _clamp(limit, default=50, maximum=200)
        off = max(0, int(offset or 0))
        page = items[off : off + lim]
        return _dumps(
            {
                "items": [source_service.public_view(s) for s in page],
                "total": total,
                "limit": lim,
                "offset": off,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)

@mcp.tool()
def get_source(authorization: str, source_locator_key: str) -> str:
    """Get Source detail by locator (sources:read)."""
    try:
        user, _token_id = _actor_from_token(authorization)
        _require(user, "sources:read")
        s = catalog_refs.resolve_source_ref(source_locator_key)
        return _dumps(source_service.public_view(s))
    except Exception as exc:  # noqa: BLE001
        return _err(exc)

@mcp.tool()
def list_objects(
    authorization: str,
    source_locator_key: str,
    q: str | None = None,
    object_type: str | None = None,
    business_semantics_ready: bool | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> str:
    """List Catalog Objects under a Source locator (metadata:read)."""
    try:
        user, _token_id = _actor_from_token(authorization)
        _require(user, "metadata:read")
        source = catalog_refs.resolve_source_ref(source_locator_key)
        lim = _clamp(limit, default=100, maximum=500)
        off = max(0, int(offset or 0))
        items, total = catalog_reads.list_objects_for_source(
            source.id,
            q=q,
            object_type=object_type,
            business_semantics_ready=business_semantics_ready,
            limit=lim,
            offset=off,
        )
        return _dumps(
            {
                "items": [_object_payload(o, include_columns=False) for o in items],
                "total": total,
                "limit": lim,
                "offset": off,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)

@mcp.tool()
def get_object(authorization: str, object_locator_key: str) -> str:
    """Get Catalog Object with columns by locator (metadata:read)."""
    try:
        user, _token_id = _actor_from_token(authorization)
        _require(user, "metadata:read")
        view = catalog_reads.get_object(object_locator_key)
        return _dumps(_object_payload(view, include_columns=True))
    except Exception as exc:  # noqa: BLE001
        return _err(exc)

@mcp.tool()
def get_object_ddl(authorization: str, object_locator_key: str) -> str:
    """Get stored DDL for a Catalog Object (metadata:read)."""
    try:
        user, _token_id = _actor_from_token(authorization)
        _require(user, "metadata:read")
        ddl = catalog_reads.get_object_ddl(object_locator_key)
        return _dumps({"id": ddl.id, "locator_key": ddl.locator_key, "ddl": ddl.ddl})
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@mcp.tool()
def get_job(authorization: str, job_id: str) -> str:
    """Get Job status (jobs:run)."""
    try:
        user, _token_id = _actor_from_token(authorization)
        _require(user, "jobs:run")
        record = get_job_store().get(job_id)
        if record is None:

            raise JobNotFound()
        return _dumps(
            {
                "id": record.id,
                "kind": record.kind,
                "status": record.status,
                "input": record.input,
                "summary": record.summary,
                "result": record.result,
                "error_code": record.error_code,
                "error_message": record.error_summary,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)

@mcp.tool()
def get_object_semantics(authorization: str, object_locator_key: str) -> str:
    """Compact object semantics by locator (metadata:read)."""
    try:
        user, _token_id = _actor_from_token(authorization)
        _require(user, "metadata:read")
        view = catalog_semantics.get_object_semantics(object_locator_key)
        return _dumps(
            {
                "locator_key": view.locator_key,
                "business_name": view.business_name,
                "business_description": view.business_description,
                "object_category": view.object_category,
                "grain_description": view.grain_description,
                "business_primary_key": view.business_primary_key,
                "business_domain": (
                    asdict(view.business_domain) if view.business_domain else None
                ),
                "evidence_summary": view.evidence_summary,
                "open_questions": view.open_questions,
                "semantic_source": view.semantic_source,
                "business_semantics_ready": view.business_semantics_ready,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)

@mcp.tool()
def set_object_semantics(
    authorization: str,
    object_locator_key: str,
    business_name: str | None = None,
    business_description: str | None = None,
    object_category: str | None = None,
    grain_description: str | None = None,
    business_primary_key: list[str] | None = None,
    business_domain_code: str | None = None,
    evidence_summary: list[str] | None = None,
    open_questions: list[str] | None = None,
) -> str:
    """Incremental object semantics write (metadata:write, semantic_source=mcp)."""
    try:
        user, token_id = _actor_from_token(authorization)
        _require(user, "metadata:write")
        o = catalog_refs.resolve_object_ref(object_locator_key)
        data = _mcp_strip_empty(
            {
                "business_name": business_name,
                "business_description": business_description,
                "object_category": object_category,
                "grain_description": grain_description,
                "business_primary_key": business_primary_key,
                "business_domain_code": business_domain_code,
                "evidence_summary": evidence_summary,
                "open_questions": open_questions,
            }
        )
        record = catalog_semantics.patch_object_semantics(
            object_id=o.id,
            data=data,
            actor_user_id=user.id,
            actor_token_id=token_id,
            semantic_source="mcp",
        )
        return _dumps(
            {
                "object": _object_payload(
                    catalog_views.object_view(record, include_columns=False),
                    include_columns=False,
                )
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)

@mcp.tool()
def set_column_semantics(
    authorization: str,
    object_locator_key: str,
    columns: list[dict[str, Any]],
) -> str:
    """Batch column semantics under one object locator (metadata:write)."""
    try:
        user, token_id = _actor_from_token(authorization)
        _require(user, "metadata:write")
        o = catalog_refs.resolve_object_ref(object_locator_key)
        stripped_columns: list[dict[str, Any]] = []
        for item in columns:
            name = item.get("column_name")
            rest = {k: v for k, v in item.items() if k != "column_name"}
            cleaned = _mcp_strip_empty(rest)
            cleaned["column_name"] = name
            stripped_columns.append(cleaned)
        result = catalog_semantics.set_column_semantics_batch(
            object_id=o.id,
            columns=stripped_columns,
            actor_user_id=user.id,
            actor_token_id=token_id,
            semantic_source="mcp",
        )
        return _dumps(result)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)

@mcp.tool()
def list_business_domains(
    authorization: str,
    query_text: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> str:
    """List Business Domains (metadata:read)."""
    try:
        user, _token_id = _actor_from_token(authorization)
        _require(user, "metadata:read")

        lim = _clamp(limit, default=100, maximum=500)
        off = max(0, int(offset or 0))
        items, total = domain_service.list_domains(
            q=query_text, limit=lim, offset=off
        )
        return _dumps(
            {
                "items": [
                    {
                        "id": d.id,
                        "code": d.code,
                        "name": d.name,
                        "description": d.description,
                        "created_at": d.created_at,
                        "updated_at": d.updated_at,
                    }
                    for d in items
                ],
                "total": total,
                "limit": lim,
                "offset": off,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)

@mcp.tool()
def create_business_domain(
    authorization: str,
    code: str,
    name: str,
    description: str | None = None,
) -> str:
    """Create a Business Domain (metadata:write)."""
    try:
        user, token_id = _actor_from_token(authorization)
        _require(user, "metadata:write")

        record = domain_service.create_domain(
            code=code,
            name=name,
            description=description,
            actor_user_id=user.id,
            actor_token_id=token_id,
        )
        return _dumps(
            {
                "domain": {
                    "id": record.id,
                    "code": record.code,
                    "name": record.name,
                    "description": record.description,
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                }
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)

@mcp.tool()
def search_objects(
    authorization: str,
    query_text: str | None = None,
    source_locator_key: str | None = None,
    object_type: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> str:
    """Cross-Source object search (metadata:read)."""
    try:
        user, _token_id = _actor_from_token(authorization)
        _require(user, "metadata:read")
        source_id = None
        if source_locator_key:
            source_id = catalog_refs.resolve_source_ref(source_locator_key).id
        lim = _clamp(limit, default=20, maximum=100)
        off = max(0, int(offset or 0))
        items, total = catalog_reads.search_objects(
            query_text or "",
            source_id=source_id,
            object_type=object_type,
            limit=lim,
            offset=off,
        )
        return _dumps(
            {
                "items": [_object_payload(o, include_columns=False) for o in items],
                "total": total,
                "limit": lim,
                "offset": off,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)

@mcp.tool()
def search_columns(
    authorization: str,
    query_text: str,
    source_locator_key: str | None = None,
    object_type: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> str:
    """Cross-Source column search (metadata:read)."""
    try:
        user, _token_id = _actor_from_token(authorization)
        _require(user, "metadata:read")
        source_id = None
        if source_locator_key:
            source_id = catalog_refs.resolve_source_ref(source_locator_key).id
        lim = _clamp(limit, default=20, maximum=100)
        off = max(0, int(offset or 0))
        items, total = catalog_reads.search_columns(
            query_text or "",
            source_id=source_id,
            object_type=object_type,
            limit=lim,
            offset=off,
        )
        return _dumps(
            {
                "items": [catalog_views.column_view_as_dict(c) for c in items],
                "total": total,
                "limit": lim,
                "offset": off,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)

@mcp.tool()
def list_joins(
    authorization: str,
    object_locator_key: str,
    limit: int | None = None,
    offset: int | None = None,
) -> str:
    """List joins for an object locator (metadata:read)."""
    try:
        user, _token_id = _actor_from_token(authorization)
        _require(user, "metadata:read")
        o = catalog_refs.resolve_object_ref(object_locator_key)
        lim = _clamp(limit, default=50, maximum=200)
        off = max(0, int(offset or 0))
        items, total = catalog_joins.list_joins(o.id, limit=lim, offset=off)
        return _dumps(
            {
                "items": [catalog_views.join_view_as_dict(j) for j in items],
                "total": total,
                "limit": lim,
                "offset": off,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)

@mcp.tool()
def upsert_join(
    authorization: str,
    from_column_locator_key: str,
    to_column_locator_key: str,
    evidence: str,
    join_kind: str | None = "INNER",
    join_expression: str | None = None,
) -> str:
    """Upsert a join edge (metadata:write, origin=mcp)."""
    try:
        user, token_id = _actor_from_token(authorization)
        _require(user, "metadata:write")
        from_col = catalog_refs.resolve_column_ref(from_column_locator_key)
        to_col = catalog_refs.resolve_column_ref(to_column_locator_key)
        record = catalog_joins.upsert_join(
            from_column_id=from_col.id,
            to_column_id=to_col.id,
            evidence=evidence,
            actor_user_id=user.id,
            actor_token_id=token_id,
            join_kind=join_kind or "INNER",
            join_expression=join_expression,
            origin="mcp",
        )
        return _dumps({"join": _join_payload_from_record(record)})
    except Exception as exc:  # noqa: BLE001
        return _err(exc)

@mcp.tool()
def upsert_joins(
    authorization: str,
    joins: list[dict[str, Any]],
) -> str:
    """Batch upsert joins; all same Source (metadata:write, origin=mcp)."""
    try:
        user, token_id = _actor_from_token(authorization)
        _require(user, "metadata:write")
        normalized: list[dict[str, Any]] = []
        skipped_joins: list[dict[str, Any]] = []
        for item in joins:
            from_ref = item.get("from_column_locator_key") or item.get("from_column_id")
            to_ref = item.get("to_column_locator_key") or item.get("to_column_id")
            if not from_ref or not to_ref:
                skipped_joins.append(
                    {
                        "reason": "missing_endpoint",
                        "from_column_locator_key": item.get("from_column_locator_key"),
                        "to_column_locator_key": item.get("to_column_locator_key"),
                        "from_column_id": item.get("from_column_id"),
                        "to_column_id": item.get("to_column_id"),
                    }
                )
                continue
            from_col = catalog_refs.resolve_column_ref(str(from_ref))
            to_col = catalog_refs.resolve_column_ref(str(to_ref))
            normalized.append(
                {
                    "from_column_id": from_col.id,
                    "to_column_id": to_col.id,
                    "evidence": item.get("evidence") or "",
                    "join_kind": item.get("join_kind") or "INNER",
                    "join_expression": item.get("join_expression"),
                }
            )
        if joins and not normalized:
            return _dumps(
                {
                    "error": {
                        "code": "JOIN_BATCH_EMPTY",
                        "message": "No valid join endpoints in batch",
                    },
                    "created_count": 0,
                    "already_known_count": 0,
                    "skipped_count": len(skipped_joins),
                    "skipped_joins": skipped_joins,
                    "items": [],
                }
            )
        items, created, known = catalog_joins.upsert_joins_batch(
            joins=normalized,
            actor_user_id=user.id,
            actor_token_id=token_id,
            origin="mcp",
        )
        return _dumps(
            {
                "created_count": created,
                "already_known_count": known,
                "skipped_count": len(skipped_joins),
                "skipped_joins": skipped_joins,
                "items": [_join_payload_from_record(j) for j in items],
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)

@mcp.tool()
def delete_join(authorization: str, join_id: str) -> str:
    """Remove a join edge by id (metadata:write)."""
    try:
        user, token_id = _actor_from_token(authorization)
        _require(user, "metadata:write")
        catalog_joins.delete_join(
            join_id=join_id,
            actor_user_id=user.id,
            actor_token_id=token_id,
        )
        return _dumps({"ok": True, "id": join_id})
    except Exception as exc:  # noqa: BLE001
        return _err(exc)

@mcp.tool()
def find_join_path(
    authorization: str,
    start_locator_key: str,
    target_locator_key: str | None = None,
    max_hops: int | None = None,
    top_targets: int | None = None,
) -> str:
    """Join path lookup from start locator (metadata:read)."""
    try:
        user, _token_id = _actor_from_token(authorization)
        _require(user, "metadata:read")
        result = catalog_reads.lookup_join_paths(
            start_locator_key,
            target_locator_key,
            max_hops=_clamp(max_hops, default=1, maximum=5),
            top_targets=_clamp(top_targets, default=3, maximum=20),
        )
        return _dumps(
            {
                "paths_found": result.paths_found,
                "paths": [
                    {
                        "target_object_id": path.target_object_id,
                        "target_column_id": path.target_column_id,
                        "hops": [asdict(hop) for hop in path.hops],
                        "path_summary": path.path_summary,
                    }
                    for path in result.paths
                ],
                "direct_joins": [
                    catalog_views.join_view_as_dict(j) for j in result.direct_joins
                ],
                "reason": result.reason,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)

@mcp.tool(
    annotations=ToolAnnotations(read_only_hint=True),
)
def run_sql(
    authorization: str,
    source_locator_key: str,
    sql: str,
    max_rows: int | None = None,
) -> str:
    """Run a single read-only SELECT against a Source (query:run)."""
    try:
        user, token_id = _actor_from_token(authorization)
        _require(user, "query:run")
        source = catalog_refs.resolve_source_ref(source_locator_key)
        outcome = query_service.run_controlled_query(
            source_id=source.id,
            sql=sql,
            max_rows=max_rows,
            actor_user_id=user.id,
            actor_token_id=token_id,
        )
        return _dumps(
            {
                "columns": outcome.columns,
                "rows": outcome.rows,
                "truncated": outcome.truncated,
                "duration_ms": outcome.duration_ms,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)

def main() -> None:
    mcp.run()

if __name__ == "__main__":
    main()
