"""Metadata MCP tools — locator-first; same domain services/permissions as HTTP."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from backend.admin.deps import resolve_pat_bearer
from backend.admin.errors import AuthForbidden, AuthUnauthenticated
from backend.admin.permissions import permissions_include
from backend.admin.role_store import get_role_store
from backend.admin.user_store import UserRecord
from backend.core.errors import AppError
from backend.jobs.store import get_job_store
from backend.metadata.catalog import service as catalog_service
from backend.metadata.catalog.store import get_catalog_store
from backend.metadata.errors import CatalogColumnNotFound
from backend.metadata.joins.graph import find_join_paths
from backend.metadata.query import service as query_service
from backend.metadata.source_jobs import enqueue_structure_job as enqueue_structure
from backend.metadata.sources import service as source_service
from backend.metadata.sources.store import get_source_store

mcp = MCPServer("refraq-metadata")


def _actor_from_token(authorization: str | None) -> tuple[UserRecord, str]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthUnauthenticated()
    token = authorization.split(" ", 1)[1].strip()
    return resolve_pat_bearer(token)


def _require(user: UserRecord, permission: str) -> None:
    roles = get_role_store()
    role = roles.get_by_id(user.role_id) if user.role_id else None
    perms = list(role.permissions) if role else []
    if not permissions_include(perms, permission):
        raise AuthForbidden(f"Missing permission {permission}")


def _err(exc: Exception) -> str:
    if isinstance(exc, AppError):
        return json.dumps({"error": {"code": exc.code, "message": exc.message}})
    return json.dumps({"error": {"code": "MCP_ERROR", "message": str(exc)}})


def _json_default(obj: object) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=_json_default)


def _clamp(value: int | None, *, default: int, maximum: int) -> int:
    if value is None:
        return default
    return max(1, min(maximum, int(value)))


def _object_payload(o: Any, *, include_columns: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": o.id,
        "locator_key": o.locator_key,
        "source_id": o.source_id,
        "object_type": o.object_type,
        "schema_name": o.schema_name,
        "name": o.name,
        "comment": o.comment,
        "primary_key": o.primary_key,
        "business_name": o.business_name,
        "business_description": o.business_description,
        "object_category": o.object_category,
        "grain_description": o.grain_description,
        "business_primary_key": o.business_primary_key,
        "time_semantics": o.time_semantics,
        "status_semantics": o.status_semantics,
        "relation_summary": o.relation_summary,
        "business_domain": o.business_domain,
        "evidence_summary": o.evidence_summary,
        "confidence": o.confidence,
        "open_questions": o.open_questions,
        "semantic_source": o.semantic_source,
        "business_semantics_ready": o.business_semantics_ready,
        "semantics_updated_at": o.semantics_updated_at,
        "is_present": o.is_present,
        "collected_at": o.collected_at,
    }
    if include_columns:
        payload["ddl"] = o.ddl
        payload["columns"] = [_column_payload(c) for c in o.columns]
    return payload


def _column_payload(c: Any) -> dict[str, Any]:
    return {
        "id": c.id,
        "locator_key": c.locator_key,
        "name": c.name,
        "data_type": c.data_type,
        "nullable": c.nullable,
        "default_value": c.default_value,
        "comment": c.comment,
        "business_name": c.business_name,
        "business_description": c.business_description,
        "column_semantics": c.column_semantics,
        "enum_catalog": c.enum_catalog,
        "semantic_source": c.semantic_source,
        "field_kind": c.field_kind,
        "ordinal": c.ordinal,
        "is_present": c.is_present,
    }


def _join_payload(j: Any, *, store) -> dict[str, Any]:
    from_col = store.get_column(j.from_column_id)
    to_col = store.get_column(j.to_column_id)
    return {
        "id": j.id,
        "from_column_id": j.from_column_id,
        "to_column_id": j.to_column_id,
        "from_column_locator_key": from_col.locator_key if from_col else None,
        "to_column_locator_key": to_col.locator_key if to_col else None,
        "evidence": j.evidence,
        "join_kind": j.join_kind,
        "join_expression": j.join_expression,
        "origin": j.origin,
        "created_by_user_id": j.created_by_user_id,
        "created_at": j.created_at,
    }


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
        items = get_source_store().list_sources()
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
        s = catalog_service.resolve_source_ref(source_locator_key)
        return _dumps(source_service.public_view(s))
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@mcp.tool()
def list_objects(
    authorization: str,
    source_locator_key: str,
    q: str | None = None,
    object_type: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> str:
    """List Catalog Objects under a Source locator (metadata:read)."""
    try:
        user, _token_id = _actor_from_token(authorization)
        _require(user, "metadata:read")
        source = catalog_service.resolve_source_ref(source_locator_key)
        lim = _clamp(limit, default=100, maximum=500)
        off = max(0, int(offset or 0))
        items, total = get_catalog_store().list_objects(
            source.id,
            name_search=q,
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
def get_object(authorization: str, object_locator_key: str) -> str:
    """Get Catalog Object with columns by locator (metadata:read)."""
    try:
        user, _token_id = _actor_from_token(authorization)
        _require(user, "metadata:read")
        o = catalog_service.resolve_object_ref(object_locator_key)
        return _dumps(_object_payload(o, include_columns=True))
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@mcp.tool()
def get_object_ddl(authorization: str, object_locator_key: str) -> str:
    """Get stored DDL for a Catalog Object (metadata:read)."""
    try:
        user, _token_id = _actor_from_token(authorization)
        _require(user, "metadata:read")
        o = catalog_service.resolve_object_ref(object_locator_key)
        return _dumps({"id": o.id, "locator_key": o.locator_key, "ddl": o.ddl})
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@mcp.tool()
def enqueue_structure_job(
    authorization: str,
    source_locator_key: str,
) -> str:
    """Enqueue a structure Job via Source facade (jobs:run)."""
    try:
        user, token_id = _actor_from_token(authorization)
        _require(user, "jobs:run")
        source = catalog_service.resolve_source_ref(source_locator_key)
        stored = enqueue_structure(
            source_id=source.id,
            actor_user_id=user.id,
            actor_token_id=token_id,
        )
        return _dumps(
            {
                "id": stored.id,
                "kind": stored.kind,
                "status": stored.status,
                "input": stored.input,
            }
        )
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
            from backend.jobs.errors import JobNotFound

            raise JobNotFound()
        return _dumps(
            {
                "id": record.id,
                "kind": record.kind,
                "status": record.status,
                "input": record.input,
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
        o = catalog_service.resolve_object_ref(object_locator_key)
        return _dumps(
            {
                "locator_key": o.locator_key,
                "business_name": o.business_name,
                "business_description": o.business_description,
                "object_category": o.object_category,
                "grain_description": o.grain_description,
                "business_primary_key": o.business_primary_key,
                "time_semantics": o.time_semantics,
                "status_semantics": o.status_semantics,
                "relation_summary": o.relation_summary,
                "business_domain": o.business_domain,
                "evidence_summary": o.evidence_summary,
                "confidence": o.confidence,
                "open_questions": o.open_questions,
                "semantic_source": o.semantic_source,
                "business_semantics_ready": o.business_semantics_ready,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@mcp.tool()
def inspect_object(authorization: str, object_locator_key: str) -> str:
    """Object semantics + columns aggregate (metadata:read)."""
    try:
        user, _token_id = _actor_from_token(authorization)
        _require(user, "metadata:read")
        o = catalog_service.resolve_object_ref(object_locator_key)
        return _dumps(_object_payload(o, include_columns=True))
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
    time_semantics: dict[str, Any] | None = None,
    status_semantics: dict[str, Any] | None = None,
    relation_summary: dict[str, Any] | None = None,
    business_domain: str | None = None,
    evidence_summary: list[str] | None = None,
    confidence: float | None = None,
    open_questions: list[str] | None = None,
) -> str:
    """Incremental object semantics write (metadata:write, semantic_source=mcp)."""
    try:
        user, token_id = _actor_from_token(authorization)
        _require(user, "metadata:write")
        o = catalog_service.resolve_object_ref(object_locator_key)
        data: dict[str, Any] = {}
        locals_map = {
            "business_name": business_name,
            "business_description": business_description,
            "object_category": object_category,
            "grain_description": grain_description,
            "business_primary_key": business_primary_key,
            "time_semantics": time_semantics,
            "status_semantics": status_semantics,
            "relation_summary": relation_summary,
            "business_domain": business_domain,
            "evidence_summary": evidence_summary,
            "confidence": confidence,
            "open_questions": open_questions,
        }
        for key, value in locals_map.items():
            if value is not None:
                data[key] = value
        record = catalog_service.patch_object_semantics(
            object_id=o.id,
            data=data,
            actor_user_id=user.id,
            actor_token_id=token_id,
            semantic_source="mcp",
        )
        return _dumps({"object": _object_payload(record, include_columns=False)})
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
        o = catalog_service.resolve_object_ref(object_locator_key)
        result = catalog_service.set_column_semantics_batch(
            object_id=o.id,
            columns=columns,
            actor_user_id=user.id,
            actor_token_id=token_id,
            semantic_source="mcp",
        )
        return _dumps(result)
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
            source_id = catalog_service.resolve_source_ref(source_locator_key).id
        query = (query_text or "").strip()
        if not query:
            from backend.metadata.errors import CatalogSearchQueryRequired

            raise CatalogSearchQueryRequired()
        lim = _clamp(limit, default=20, maximum=100)
        off = max(0, int(offset or 0))
        items, total = get_catalog_store().search_objects(
            query,
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
            source_id = catalog_service.resolve_source_ref(source_locator_key).id
        query = (query_text or "").strip()
        if not query:
            from backend.metadata.errors import CatalogSearchQueryRequired

            raise CatalogSearchQueryRequired()
        lim = _clamp(limit, default=20, maximum=100)
        off = max(0, int(offset or 0))
        items, total = get_catalog_store().search_columns(
            query,
            source_id=source_id,
            object_type=object_type,
            limit=lim,
            offset=off,
        )
        return _dumps(
            {
                "items": [_column_payload(c) for c in items],
                "total": total,
                "limit": lim,
                "offset": off,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@mcp.tool()
def list_joins(authorization: str, object_locator_key: str) -> str:
    """List joins for an object locator (metadata:read)."""
    try:
        user, _token_id = _actor_from_token(authorization)
        _require(user, "metadata:read")
        o = catalog_service.resolve_object_ref(object_locator_key)
        store = get_catalog_store()
        items = catalog_service.list_joins(o.id)
        return _dumps({"items": [_join_payload(j, store=store) for j in items]})
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
        from_col = catalog_service.resolve_column_ref(from_column_locator_key)
        to_col = catalog_service.resolve_column_ref(to_column_locator_key)
        record = catalog_service.upsert_join(
            from_column_id=from_col.id,
            to_column_id=to_col.id,
            evidence=evidence,
            actor_user_id=user.id,
            actor_token_id=token_id,
            join_kind=join_kind or "INNER",
            join_expression=join_expression,
            origin="mcp",
        )
        return _dumps({"join": _join_payload(record, store=get_catalog_store())})
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
            from_col = catalog_service.resolve_column_ref(str(from_ref))
            to_col = catalog_service.resolve_column_ref(str(to_ref))
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
        items, created, known = catalog_service.upsert_joins_batch(
            joins=normalized,
            actor_user_id=user.id,
            actor_token_id=token_id,
            origin="mcp",
        )
        store = get_catalog_store()
        return _dumps(
            {
                "created_count": created,
                "already_known_count": known,
                "skipped_count": len(skipped_joins),
                "skipped_joins": skipped_joins,
                "items": [_join_payload(j, store=store) for j in items],
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
        catalog_service.delete_join(
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
        store = get_catalog_store()
        start_object_id = None
        start_column_id = None
        try:
            start_col = catalog_service.resolve_column_ref(start_locator_key)
            start_column_id = start_col.id
        except CatalogColumnNotFound:
            start_obj = catalog_service.resolve_object_ref(start_locator_key)
            start_object_id = start_obj.id

        target_object_id = None
        target_column_id = None
        if target_locator_key:
            try:
                t_col = catalog_service.resolve_column_ref(target_locator_key)
                target_column_id = t_col.id
            except CatalogColumnNotFound:
                t_obj = catalog_service.resolve_object_ref(target_locator_key)
                target_object_id = t_obj.id

        result = find_join_paths(
            store=store,
            start_object_id=start_object_id,
            start_column_id=start_column_id,
            target_object_id=target_object_id,
            target_column_id=target_column_id,
            max_hops=_clamp(max_hops, default=1, maximum=5),
            top_targets=_clamp(top_targets, default=3, maximum=20),
        )
        if result.reason == "NO_START_COLUMNS":
            from backend.metadata.errors import JoinPathUnavailable

            raise JoinPathUnavailable()
        paths = []
        for path in result.paths:
            hops = []
            for hop in path.hops:
                from_col = store.get_column(hop.from_column_id)
                to_col = store.get_column(hop.to_column_id)
                hops.append(
                    {
                        "from_column_id": hop.from_column_id,
                        "to_column_id": hop.to_column_id,
                        "from_column_locator_key": (
                            from_col.locator_key if from_col else None
                        ),
                        "to_column_locator_key": (
                            to_col.locator_key if to_col else None
                        ),
                        "join_id": hop.join.id,
                        "join_kind": hop.join.join_kind,
                        "join_expression": hop.join.join_expression,
                        "evidence": hop.join.evidence,
                        "origin": hop.join.origin,
                    }
                )
            paths.append(
                {
                    "target_object_id": path.target_object_id,
                    "target_column_id": path.target_column_id,
                    "hops": hops,
                    "path_summary": path.path_summary,
                }
            )
        return _dumps(
            {
                "paths_found": len(paths),
                "paths": paths,
                "direct_joins": [
                    _join_payload(j, store=store) for j in result.direct_joins
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
        source = catalog_service.resolve_source_ref(source_locator_key)
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
