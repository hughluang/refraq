"""Saved Filter HTTP, mounted with the Tag collection."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status

from backend.admin.deps import get_current_user, resolve_user_permissions
from backend.admin.errors import AuthForbidden
from backend.admin.permissions import permissions_include
from backend.admin.role_store import RoleStore, get_role_store
from backend.admin.user_store import UserRecord
from backend.core.pagination import PageParams, page_params
from backend.tags.saved_filters import (
    create_saved_filter,
    delete_saved_filter,
    owned_visible,
    remember_saved_filter,
    update_saved_filter,
)
from backend.tags.saved_filter_store import SavedFilterRecord, get_saved_filter_store
from backend.tags.schemas.saved_filters import (
    SavedFilterCreateRequest,
    SavedFilterDefaultOut,
    SavedFilterDefaultPut,
    SavedFilterListResponse,
    SavedFilterOut,
    SavedFilterPatchRequest,
    SavedFilterResponse,
)

router = APIRouter(tags=["tags"])

_PAGE = page_params(default_limit=50, max_limit=50)


def _require_list_read(list_name: str, user: UserRecord, roles: RoleStore) -> None:
    key = "entity:read" if list_name == "entities" else "channel:read"
    perms = resolve_user_permissions(user, roles)
    if not permissions_include(perms, key):
        raise AuthForbidden()


def _out(record: SavedFilterRecord) -> SavedFilterOut:
    return SavedFilterOut(
        id=record.id,
        list=record.list_name,
        name=record.name,
        query=record.query,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("/saved-filters", response_model=SavedFilterListResponse)
def http_list_saved_filters(
    list_name: Literal["entities", "channels"] = Query(alias="list"),
    page: PageParams = Depends(_PAGE),
    user: UserRecord = Depends(get_current_user),
    roles: RoleStore = Depends(get_role_store),
) -> SavedFilterListResponse:
    _require_list_read(list_name, user, roles)
    items, total = get_saved_filter_store().list_for_user(
        user.id,
        list_name,
        limit=page.limit,
        offset=page.offset,
    )
    return SavedFilterListResponse(
        items=[_out(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/saved-filters",
    response_model=SavedFilterResponse,
    status_code=status.HTTP_201_CREATED,
)
def http_create_saved_filter(
    body: SavedFilterCreateRequest,
    user: UserRecord = Depends(get_current_user),
    roles: RoleStore = Depends(get_role_store),
) -> SavedFilterResponse:
    _require_list_read(body.list, user, roles)
    record = create_saved_filter(
        user_id=user.id,
        list_name=body.list,
        name=body.name,
        query=body.query,
    )
    return SavedFilterResponse(saved_filter=_out(record))


@router.get("/saved-filters/default", response_model=SavedFilterDefaultOut)
def http_get_saved_filter_default(
    list_name: Literal["entities", "channels"] = Query(alias="list"),
    user: UserRecord = Depends(get_current_user),
    roles: RoleStore = Depends(get_role_store),
) -> SavedFilterDefaultOut:
    _require_list_read(list_name, user, roles)
    return SavedFilterDefaultOut(
        list=list_name,
        saved_filter_id=get_saved_filter_store().get_default(user.id, list_name),
    )


@router.put("/saved-filters/default", response_model=SavedFilterDefaultOut)
def http_put_saved_filter_default(
    body: SavedFilterDefaultPut,
    user: UserRecord = Depends(get_current_user),
    roles: RoleStore = Depends(get_role_store),
) -> SavedFilterDefaultOut:
    _require_list_read(body.list, user, roles)
    remember_saved_filter(
        user_id=user.id,
        list_name=body.list,
        saved_filter_id=body.saved_filter_id,
    )
    return SavedFilterDefaultOut(list=body.list, saved_filter_id=body.saved_filter_id)


@router.patch("/saved-filters/{filter_id}", response_model=SavedFilterResponse)
def http_patch_saved_filter(
    filter_id: str,
    body: SavedFilterPatchRequest,
    user: UserRecord = Depends(get_current_user),
    roles: RoleStore = Depends(get_role_store),
) -> SavedFilterResponse:
    current = owned_visible(get_saved_filter_store().get(filter_id), user.id)
    _require_list_read(current.list_name, user, roles)
    record = update_saved_filter(
        filter_id,
        user_id=user.id,
        name=body.name,
        name_set="name" in body.model_fields_set,
        query=body.query,
        query_set="query" in body.model_fields_set,
    )
    return SavedFilterResponse(saved_filter=_out(record))


@router.delete(
    "/saved-filters/{filter_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def http_delete_saved_filter(
    filter_id: str,
    user: UserRecord = Depends(get_current_user),
    roles: RoleStore = Depends(get_role_store),
) -> Response:
    current = owned_visible(get_saved_filter_store().get(filter_id), user.id)
    _require_list_read(current.list_name, user, roles)
    delete_saved_filter(filter_id, user_id=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
