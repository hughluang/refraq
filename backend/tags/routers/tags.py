"""Tag collection HTTP."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status

from backend.admin.deps import (
    get_actor_token_id,
    get_current_user,
    require_permission,
    resolve_user_permissions,
)
from backend.admin.errors import AuthForbidden
from backend.admin.permissions import permissions_include
from backend.admin.role_store import RoleStore, get_role_store
from backend.admin.user_store import UserRecord
from backend.core.pagination import PageParams, page_params
from backend.tags.records import TagRecord
from backend.tags.schemas.tags import (
    TagCreateRequest,
    TagDetail,
    TagListResponse,
    TagOut,
    TagPatchRequest,
    TagResponse,
)
from backend.tags.service import create_tag, delete_tag, get_tag, update_tag
from backend.tags.store import get_tag_store

router = APIRouter(tags=["tags"])

_LIST_PAGE = page_params(default_limit=50, max_limit=200)
_LIST_PERMISSIONS = ("tag:read", "entity:read", "channel:read")


def require_tag_list_access(
    user: UserRecord = Depends(get_current_user),
    roles: RoleStore = Depends(get_role_store),
) -> UserRecord:
    perms = resolve_user_permissions(user, roles)
    if any(permissions_include(perms, key) for key in _LIST_PERMISSIONS):
        return user
    raise AuthForbidden()


def _summary(record: TagRecord) -> TagOut:
    return TagOut(
        id=record.id,
        name=record.name,
        description=record.description,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _detail(record: TagRecord) -> TagDetail:
    return TagDetail(
        id=record.id,
        name=record.name,
        description=record.description,
        created_at=record.created_at,
        updated_at=record.updated_at,
        entity_count=0,
        channel_count=0,
    )


@router.get("/tags", response_model=TagListResponse)
def http_list_tags(
    q: str | None = Query(default=None),
    page: PageParams = Depends(_LIST_PAGE),
    _: UserRecord = Depends(require_tag_list_access),
) -> TagListResponse:
    items, total = get_tag_store().list_tags(q=q, limit=page.limit, offset=page.offset)
    return TagListResponse(
        items=[_summary(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/tags",
    response_model=TagResponse,
    status_code=status.HTTP_201_CREATED,
)
def http_create_tag(
    body: TagCreateRequest,
    user: UserRecord = Depends(require_permission("tag:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> TagResponse:
    record = create_tag(
        name=body.name,
        description=body.description,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return TagResponse(tag=_detail(record))


@router.get("/tags/{tag_id}", response_model=TagResponse)
def http_get_tag(
    tag_id: str,
    _: UserRecord = Depends(require_permission("tag:read")),
) -> TagResponse:
    return TagResponse(tag=_detail(get_tag(tag_id)))


@router.patch("/tags/{tag_id}", response_model=TagResponse)
def http_patch_tag(
    tag_id: str,
    body: TagPatchRequest,
    user: UserRecord = Depends(require_permission("tag:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> TagResponse:
    record = update_tag(
        tag_id,
        name=body.name,
        name_set="name" in body.model_fields_set,
        description=body.description,
        description_set="description" in body.model_fields_set,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return TagResponse(tag=_detail(record))


@router.delete(
    "/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def http_delete_tag(
    tag_id: str,
    user: UserRecord = Depends(require_permission("tag:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> Response:
    delete_tag(
        tag_id,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
