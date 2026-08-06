"""Slice A MCP tools — same domain services and permissions as HTTP."""

from __future__ import annotations

import json
from typing import Any

from mcp.server import MCPServer

from backend.admin.deps import resolve_user_from_bearer
from backend.admin.errors import AuthError, AuthForbidden, AuthUnauthenticated
from backend.admin.permissions import permissions_include
from backend.jobs.store import get_job_store, create_queued_job
from backend.metadata.catalog.store import get_catalog_store, require_object
from backend.metadata.enqueue import enqueue_job
from backend.metadata.errors import (
    JobAlreadyActive,
    JobConnectionDisabled,
    JobSecretMissing,
    JobSourceDisabled,
    SourceNotFound,
)
from backend.metadata.sources.store import get_source_store
from backend.repositories.role_store import get_role_store
from backend.repositories.user_store import UserRecord

mcp = MCPServer("refraq-metadata")


def _user_from_token(authorization: str | None) -> UserRecord:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthUnauthenticated()
    token = authorization.split(" ", 1)[1].strip()
    return resolve_user_from_bearer(token)


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


@mcp.tool()
def search_sources(authorization: str, q: str | None = None) -> str:
    """Search/list Sources (sources:read)."""
    try:
        user = _user_from_token(authorization)
        _require(user, "sources:read")
        items = get_source_store().list_sources()
        if q:
            ql = q.lower()
            items = [
                s
                for s in items
                if ql in s.key.lower() or ql in s.name.lower()
            ]
        return json.dumps(
            {
                "items": [
                    {
                        "id": s.id,
                        "key": s.key,
                        "name": s.name,
                        "kind": s.kind,
                        "status": s.status,
                        "database_name": s.database_name,
                        "schema_filter": s.schema_filter,
                    }
                    for s in items
                ]
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@mcp.tool()
def get_source(authorization: str, source_id: str) -> str:
    """Get Source detail (sources:read)."""
    try:
        user = _user_from_token(authorization)
        _require(user, "sources:read")
        s = get_source_store().get_source(source_id)
        if s is None:
            raise SourceNotFound()
        return json.dumps(
            {
                "id": s.id,
                "key": s.key,
                "name": s.name,
                "kind": s.kind,
                "status": s.status,
                "description": s.description,
                "database_name": s.database_name,
                "schema_filter": s.schema_filter,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@mcp.tool()
def list_connections(authorization: str, source_id: str) -> str:
    """List the Source Connection if any (0 or 1; sources:read)."""
    try:
        user = _user_from_token(authorization)
        _require(user, "sources:read")
        store = get_source_store()
        if store.get_source(source_id) is None:
            raise SourceNotFound()
        conn = store.get_connection_for_source(source_id)
        items: list[dict[str, Any]] = []
        if conn:
            items.append(
                {
                    "id": conn.id,
                    "source_id": conn.source_id,
                    "name": conn.name,
                    "engine": conn.engine,
                    "host": conn.host,
                    "port": conn.port,
                    "status": conn.status,
                    "has_secret": conn.has_secret,
                }
            )
        return json.dumps({"items": items})
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@mcp.tool()
def list_objects(authorization: str, source_id: str, q: str | None = None) -> str:
    """List Catalog Objects under a Source (metadata:read)."""
    try:
        user = _user_from_token(authorization)
        _require(user, "metadata:read")
        if get_source_store().get_source(source_id) is None:
            raise SourceNotFound()
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
        user = _user_from_token(authorization)
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
        user = _user_from_token(authorization)
        _require(user, "metadata:read")
        o = require_object(object_id)
        return json.dumps({"id": o.id, "ddl": o.ddl})
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@mcp.tool()
def enqueue_structure_job(
    authorization: str,
    source_id: str,
    connection_id: str | None = None,
) -> str:
    """Enqueue a structure Job via Source facade (jobs:run)."""
    try:
        user = _user_from_token(authorization)
        _require(user, "jobs:run")
        sources = get_source_store()
        source = sources.get_source(source_id)
        if source is None:
            raise SourceNotFound()
        if source.status != "active":
            raise JobSourceDisabled()
        connection = sources.get_connection_for_source(source_id)
        if connection is None:
            raise JobSecretMissing("Source has no Connection")
        if connection_id and connection_id != connection.id:
            from backend.metadata.errors import JobConnectionMismatch

            raise JobConnectionMismatch()
        if connection.status != "active":
            raise JobConnectionDisabled()
        if not connection.has_secret:
            raise JobSecretMissing()
        if get_job_store().has_active_structure_job(source_id):
            raise JobAlreadyActive()
        job = create_queued_job(
            kind="structure",
            input={"source_id": source_id, "connection_id": connection.id},
            created_by=user.id,
        )
        enqueue_job(job)
        stored = get_job_store().get(job.id) or job
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
        user = _user_from_token(authorization)
        _require(user, "jobs:run")
        record = get_job_store().get(job_id)
        if record is None:
            from backend.metadata.errors import JobNotFound

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
