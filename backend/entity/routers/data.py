"""Entity Data API HTTP routers (POST verbs by table_name)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse

from backend.admin.deps import require_permission
from backend.admin.user_store import UserRecord
from backend.entity.data import service as data_service
from backend.entity.errors import EntityRequestInvalid

router = APIRouter(tags=["entity-data"])


async def _json_object(request: Request) -> dict[str, Any]:
    """Parse the body only after the route's auth dependency has succeeded."""
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise EntityRequestInvalid("Request validation failed") from exc
    if body is None or not isinstance(body, dict):
        raise EntityRequestInvalid("Request body must be a JSON object")
    return body


@router.post("/entities/{table_name}/schema")
async def http_schema(
    table_name: str,
    request: Request,
    user: UserRecord = Depends(require_permission("entity:data_read")),
) -> dict[str, Any]:
    return data_service.schema_for(table_name, await _json_object(request), user)


@router.post(
    "/entities/{table_name}/create",
    status_code=status.HTTP_201_CREATED,
)
async def http_create(
    table_name: str,
    request: Request,
    _read: UserRecord = Depends(require_permission("entity:data_read")),
    user: UserRecord = Depends(require_permission("entity:data_write")),
) -> dict[str, Any]:
    return {"row": data_service.create_row(table_name, await _json_object(request), user)}


@router.post(
    "/entities/{table_name}/create-many",
    status_code=status.HTTP_201_CREATED,
)
async def http_create_many(
    table_name: str,
    request: Request,
    _read: UserRecord = Depends(require_permission("entity:data_read")),
    user: UserRecord = Depends(require_permission("entity:data_write")),
) -> dict[str, Any]:
    body = await _json_object(request)
    return {"rows": data_service.create_many_rows(table_name, body, user)}


@router.post("/entities/{table_name}/get")
async def http_get(
    table_name: str,
    request: Request,
    user: UserRecord = Depends(require_permission("entity:data_read")),
) -> dict[str, Any]:
    return {"row": data_service.get_row(table_name, await _json_object(request), user)}


@router.post("/entities/{table_name}/update")
async def http_update(
    table_name: str,
    request: Request,
    _read: UserRecord = Depends(require_permission("entity:data_read")),
    user: UserRecord = Depends(require_permission("entity:data_write")),
) -> dict[str, Any]:
    return {"row": data_service.update_row(table_name, await _json_object(request), user)}


@router.post(
    "/entities/{table_name}/delete",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def http_delete(
    table_name: str,
    request: Request,
    _read: UserRecord = Depends(require_permission("entity:data_read")),
    user: UserRecord = Depends(require_permission("entity:data_write")),
) -> Response:
    data_service.delete_row(table_name, await _json_object(request), user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/entities/{table_name}/query")
async def http_query(
    table_name: str,
    request: Request,
    user: UserRecord = Depends(require_permission("entity:data_read")),
) -> dict[str, Any]:
    return data_service.query_rows(table_name, await _json_object(request), user)


@router.post("/entities/{table_name}/update-where")
async def http_update_where(
    table_name: str,
    request: Request,
    _read: UserRecord = Depends(require_permission("entity:data_read")),
    user: UserRecord = Depends(require_permission("entity:data_write")),
) -> dict[str, Any]:
    body = await _json_object(request)
    return data_service.update_where_rows(table_name, body, user)


@router.post("/entities/{table_name}/delete-where")
async def http_delete_where(
    table_name: str,
    request: Request,
    _read: UserRecord = Depends(require_permission("entity:data_read")),
    user: UserRecord = Depends(require_permission("entity:data_write")),
) -> dict[str, Any]:
    body = await _json_object(request)
    return data_service.delete_where_rows(table_name, body, user)


@router.post("/entities/{table_name}/upsert")
async def http_upsert(
    table_name: str,
    request: Request,
    _read: UserRecord = Depends(require_permission("entity:data_read")),
    user: UserRecord = Depends(require_permission("entity:data_write")),
) -> JSONResponse:
    row, created = data_service.upsert_one(
        table_name, await _json_object(request), user
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        content={"row": row},
    )
