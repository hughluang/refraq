"""Slice A MCP tools — same domain services and permissions as HTTP."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from mcp.server import MCPServer

from backend.admin.deps import resolve_pat_bearer
from backend.admin.errors import AuthError, AuthForbidden, AuthUnauthenticated
from backend.admin.permissions import permissions_include
from backend.admin.role_store import get_role_store
from backend.admin.user_store import UserRecord
from backend.jobs.store import get_job_store
from backend.metadata.catalog.store import get_catalog_store, require_object
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
    if isinstance(exc, AuthError):
        return json.dumps({"error": {"code": exc.code, "message": exc.message}})
    return json.dumps({"error": {"code": "MCP_ERROR", "message": str(exc)}})


def _json_default(obj: object) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=_json_default)


@mcp.tool()
def search_sources(authorization: str, q: str | None = None) -> str:
    """Search/list Sources (sources:read)."""
    try:
        user, _token_id = _actor_from_token(authorization)
        _require(user, "sources:read")
        items = get_source_store().list_sources()
        if q:
            ql = q.lower()
            items = [
                s
                for s in items
                if ql in s.key.lower() or ql in s.name.lower()
            ]
        return _dumps({"items": [source_service.public_view(s) for s in items]})
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@mcp.tool()
def get_source(authorization: str, source_id: str) -> str:
    """Get Source detail (sources:read)."""
    try:
        user, _token_id = _actor_from_token(authorization)
        _require(user, "sources:read")
        s = source_service.require_source(source_id)
        return _dumps(source_service.public_view(s))
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@mcp.tool()
def list_objects(authorization: str, source_id: str, q: str | None = None) -> str:
    """List Catalog Objects under a Source (metadata:read)."""
    try:
        user, _token_id = _actor_from_token(authorization)
        _require(user, "metadata:read")
        source_service.require_source(source_id)
        items = get_catalog_store().list_objects(source_id, name_search=q)
        return json.dumps(
            {
                "items": [
                    {
                        "id": o.id,
                        "source_id": o.source_id,
                        "object_type": o.object_type,
                        "schema_name": o.schema_name,
                        "name": o.name,
                        "is_present": o.is_present,
                    }
                    for o in items
                ]
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@mcp.tool()
def get_object(authorization: str, object_id: str) -> str:
    """Get Catalog Object with columns (metadata:read)."""
    try:
        user, _token_id = _actor_from_token(authorization)
        _require(user, "metadata:read")
        o = require_object(object_id)
        return json.dumps(
            {
                "id": o.id,
                "source_id": o.source_id,
                "object_type": o.object_type,
                "schema_name": o.schema_name,
                "name": o.name,
                "ddl": o.ddl,
                "is_present": o.is_present,
                "columns": [
                    {
                        "id": c.id,
                        "name": c.name,
                        "data_type": c.data_type,
                        "nullable": c.nullable,
                        "ordinal": c.ordinal,
                    }
                    for c in o.columns
                ],
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@mcp.tool()
def get_object_ddl(authorization: str, object_id: str) -> str:
    """Get stored DDL for a Catalog Object (metadata:read)."""
    try:
        user, _token_id = _actor_from_token(authorization)
        _require(user, "metadata:read")
        o = require_object(object_id)
        return json.dumps({"id": o.id, "ddl": o.ddl})
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@mcp.tool()
def enqueue_structure_job(
    authorization: str,
    source_id: str,
) -> str:
    """Enqueue a structure Job via Source facade (jobs:run)."""
    try:
        user, token_id = _actor_from_token(authorization)
        _require(user, "jobs:run")
        stored = enqueue_structure(
            source_id=source_id,
            actor_user_id=user.id,
            actor_token_id=token_id,
        )
        return json.dumps(
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
        return json.dumps(
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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
