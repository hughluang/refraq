"""Dictionary HTTP router."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord
from backend.core.pagination import ENTITY_LIST, PageParams, page_params
from backend.entity.dictionaries.service import (
    create_dictionary,
    delete_dictionary,
    get_dictionary,
    list_dictionaries,
    update_dictionary,
)
from backend.entity.schemas.dictionaries import (
    DictionaryCreateRequest,
    DictionaryListResponse,
    DictionaryOut,
    DictionaryPatchRequest,
    DictionaryResponse,
)

router = APIRouter(tags=["dictionaries"])


@router.get("/dictionaries", response_model=DictionaryListResponse)
def http_list_dictionaries(
    q: str | None = Query(default=None),
    status: list[Literal["available", "deprecated"]] | None = Query(default=None),
    page: PageParams = Depends(page_params(ENTITY_LIST)),
    _: UserRecord = Depends(require_permission("entity:read")),
) -> DictionaryListResponse:
    items, total = list_dictionaries(
        q=q, statuses=status, limit=page.limit, offset=page.offset
    )
    return DictionaryListResponse(
        items=[DictionaryOut.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/dictionaries",
    response_model=DictionaryResponse,
    status_code=status.HTTP_201_CREATED,
)
def http_create_dictionary(
    body: DictionaryCreateRequest,
    user: UserRecord = Depends(require_permission("entity:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> DictionaryResponse:
    payload = create_dictionary(
        name=body.name,
        display_name=body.display_name,
        description=body.description,
        entries=[item.model_dump() for item in body.entries],
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return DictionaryResponse(dictionary=DictionaryOut.model_validate(payload))


@router.get("/dictionaries/{dictionary_id}", response_model=DictionaryResponse)
def http_get_dictionary(
    dictionary_id: str,
    _: UserRecord = Depends(require_permission("entity:read")),
) -> DictionaryResponse:
    payload = get_dictionary(dictionary_id)
    return DictionaryResponse(dictionary=DictionaryOut.model_validate(payload))


@router.patch("/dictionaries/{dictionary_id}", response_model=DictionaryResponse)
def http_patch_dictionary(
    dictionary_id: str,
    body: DictionaryPatchRequest,
    user: UserRecord = Depends(require_permission("entity:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> DictionaryResponse:
    entries = (
        [item.model_dump() for item in body.entries]
        if body.entries is not None
        else None
    )
    payload = update_dictionary(
        dictionary_id,
        display_name=body.display_name,
        description=body.description,
        description_set="description" in body.model_fields_set,
        deprecated=body.deprecated,
        entries=entries,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return DictionaryResponse(dictionary=DictionaryOut.model_validate(payload))


@router.delete(
    "/dictionaries/{dictionary_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def http_delete_dictionary(
    dictionary_id: str,
    user: UserRecord = Depends(require_permission("entity:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> Response:
    delete_dictionary(
        dictionary_id,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
