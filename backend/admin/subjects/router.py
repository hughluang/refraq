"""User Group and Subject Attribute HTTP adapters (docs/api-contracts-users.md §8–§9)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, status

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.role_store import RoleStore, get_role_store
from backend.admin.subjects import service
from backend.admin.subjects.records import SubjectAttributeRecord, UserGroupRecord
from backend.admin.subjects.schemas import (
    SubjectAttributeCreateIn,
    SubjectAttributeList,
    SubjectAttributeOut,
    SubjectAttributePatchIn,
    SubjectAttributeResponse,
    SubjectValuesIn,
    SubjectValuesResponse,
    UserGroupCreateIn,
    UserGroupList,
    UserGroupMembersList,
    UserGroupOut,
    UserGroupPatchIn,
    UserGroupResponse,
    UserGroupsReplaceIn,
    UserGroupsResponse,
    UserSubjectValuesResponse,
)
from backend.admin.subjects.store import SubjectStore, get_subject_store
from backend.admin.user_payload import build_user_summary
from backend.admin.user_store import UserRecord
from backend.core.pagination import PageParams, page_params

router = APIRouter(tags=["subjects"])

_READ = require_permission("users:read")
_WRITE = require_permission("users:write")
_PAGE = page_params(default_limit=50, max_limit=200)


def _groups_out(store: SubjectStore, groups: list[UserGroupRecord]) -> list[UserGroupOut]:
    counts = store.member_counts(group.id for group in groups)
    return [
        UserGroupOut(
            id=group.id,
            key=group.key,
            name=group.name,
            description=group.description,
            member_count=counts.get(group.id, 0),
            created_at=group.created_at,
            updated_at=group.updated_at,
        )
        for group in groups
    ]


def _group_out(store: SubjectStore, group: UserGroupRecord) -> UserGroupResponse:
    return UserGroupResponse(group=_groups_out(store, [group])[0])


def _definition_out(record: SubjectAttributeRecord) -> SubjectAttributeOut:
    return SubjectAttributeOut(
        id=record.id,
        key=record.key,
        name=record.name,
        description=record.description,
        value_type=record.value_type,
        dictionary_id=record.dictionary_id,
        multi_value=record.multi_value,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _sent(body: Any) -> dict[str, Any]:
    return {name: getattr(body, name) for name in body.model_fields_set}


@router.get("/user-groups", response_model=UserGroupList)
def list_groups(
    q: str | None = Query(default=None),
    page: PageParams = Depends(_PAGE),
    store: SubjectStore = Depends(get_subject_store),
    _caller: UserRecord = Depends(_READ),
) -> UserGroupList:
    items, total = store.list_groups(
        q=(q or "").strip() or None, limit=page.limit, offset=page.offset
    )
    return UserGroupList(
        items=_groups_out(store, items),
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/user-groups",
    response_model=UserGroupResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_group(
    body: UserGroupCreateIn,
    caller: UserRecord = Depends(_WRITE),
    actor_token_id: str | None = Depends(get_actor_token_id),
    store: SubjectStore = Depends(get_subject_store),
) -> UserGroupResponse:
    group = service.create_group(
        key=body.key,
        name=body.name,
        description=body.description,
        actor_user_id=caller.id,
        actor_token_id=actor_token_id,
    )
    return _group_out(store, group)


@router.get("/user-groups/{group_id}", response_model=UserGroupResponse)
def get_group(
    group_id: str,
    store: SubjectStore = Depends(get_subject_store),
    _caller: UserRecord = Depends(_READ),
) -> UserGroupResponse:
    return _group_out(store, service.require_group(group_id))


@router.patch("/user-groups/{group_id}", response_model=UserGroupResponse)
def patch_group(
    group_id: str,
    body: UserGroupPatchIn,
    caller: UserRecord = Depends(_WRITE),
    actor_token_id: str | None = Depends(get_actor_token_id),
    store: SubjectStore = Depends(get_subject_store),
) -> UserGroupResponse:
    group = service.patch_group(
        group_id,
        **_sent(body),
        actor_user_id=caller.id,
        actor_token_id=actor_token_id,
    )
    return _group_out(store, group)


@router.delete("/user-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    group_id: str,
    caller: UserRecord = Depends(_WRITE),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> None:
    service.delete_group(group_id, actor_user_id=caller.id, actor_token_id=actor_token_id)


@router.get("/user-groups/{group_id}/members", response_model=UserGroupMembersList)
def list_members(
    group_id: str,
    page: PageParams = Depends(_PAGE),
    roles: RoleStore = Depends(get_role_store),
    _caller: UserRecord = Depends(_READ),
) -> UserGroupMembersList:
    members, total = service.list_member_users(
        group_id, limit=page.limit, offset=page.offset
    )
    return UserGroupMembersList(
        items=[build_user_summary(member, roles) for member in members],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.put(
    "/user-groups/{group_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def add_member(
    group_id: str,
    user_id: str,
    caller: UserRecord = Depends(_WRITE),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> None:
    service.add_member(
        group_id, user_id, actor_user_id=caller.id, actor_token_id=actor_token_id
    )


@router.delete(
    "/user-groups/{group_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_member(
    group_id: str,
    user_id: str,
    caller: UserRecord = Depends(_WRITE),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> None:
    service.remove_member(
        group_id, user_id, actor_user_id=caller.id, actor_token_id=actor_token_id
    )


@router.get(
    "/user-groups/{group_id}/subject-attributes", response_model=SubjectValuesResponse
)
def get_group_values(
    group_id: str,
    _caller: UserRecord = Depends(_READ),
) -> SubjectValuesResponse:
    service.require_group(group_id)
    return SubjectValuesResponse(values=service.own_values_of("group", group_id))


@router.put(
    "/user-groups/{group_id}/subject-attributes", response_model=SubjectValuesResponse
)
def put_group_values(
    group_id: str,
    body: SubjectValuesIn,
    caller: UserRecord = Depends(_WRITE),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> SubjectValuesResponse:
    values = service.replace_group_values(
        group_id, body.values, actor_user_id=caller.id, actor_token_id=actor_token_id
    )
    return SubjectValuesResponse(values=values)


@router.get("/users/{user_id}/groups", response_model=UserGroupsResponse)
def get_user_groups(
    user_id: str,
    store: SubjectStore = Depends(get_subject_store),
    _caller: UserRecord = Depends(_READ),
) -> UserGroupsResponse:
    service.require_user(user_id)
    return UserGroupsResponse(groups=_groups_out(store, service.user_groups_of(user_id)))


@router.put("/users/{user_id}/groups", response_model=UserGroupsResponse)
def put_user_groups(
    user_id: str,
    body: UserGroupsReplaceIn,
    caller: UserRecord = Depends(_WRITE),
    actor_token_id: str | None = Depends(get_actor_token_id),
    store: SubjectStore = Depends(get_subject_store),
) -> UserGroupsResponse:
    groups = service.replace_user_groups(
        user_id, body.group_ids, actor_user_id=caller.id, actor_token_id=actor_token_id
    )
    return UserGroupsResponse(groups=_groups_out(store, groups))


@router.get(
    "/users/{user_id}/subject-attributes", response_model=UserSubjectValuesResponse
)
def get_user_values(
    user_id: str,
    _caller: UserRecord = Depends(_READ),
) -> UserSubjectValuesResponse:
    service.require_user(user_id)
    return UserSubjectValuesResponse(
        values=service.own_values_of("user", user_id),
        effective=service.effective_values_of(user_id),
    )


@router.put(
    "/users/{user_id}/subject-attributes", response_model=UserSubjectValuesResponse
)
def put_user_values(
    user_id: str,
    body: SubjectValuesIn,
    caller: UserRecord = Depends(_WRITE),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> UserSubjectValuesResponse:
    values = service.replace_user_values(
        user_id, body.values, actor_user_id=caller.id, actor_token_id=actor_token_id
    )
    return UserSubjectValuesResponse(
        values=values, effective=service.effective_values_of(user_id)
    )


@router.get("/subject-attributes", response_model=SubjectAttributeList)
def list_definitions(
    page: PageParams = Depends(_PAGE),
    store: SubjectStore = Depends(get_subject_store),
    _caller: UserRecord = Depends(_READ),
) -> SubjectAttributeList:
    items, total = store.list_definitions(limit=page.limit, offset=page.offset)
    return SubjectAttributeList(
        items=[_definition_out(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/subject-attributes",
    response_model=SubjectAttributeResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_definition(
    body: SubjectAttributeCreateIn,
    caller: UserRecord = Depends(_WRITE),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> SubjectAttributeResponse:
    record = service.create_definition(
        key=body.key,
        name=body.name,
        description=body.description,
        value_type=body.value_type,
        dictionary_id=body.dictionary_id,
        multi_value=body.multi_value,
        actor_user_id=caller.id,
        actor_token_id=actor_token_id,
    )
    return SubjectAttributeResponse(subject_attribute=_definition_out(record))


@router.get("/subject-attributes/{definition_id}", response_model=SubjectAttributeResponse)
def get_definition(
    definition_id: str,
    _caller: UserRecord = Depends(_READ),
) -> SubjectAttributeResponse:
    return SubjectAttributeResponse(
        subject_attribute=_definition_out(service.require_definition(definition_id))
    )


@router.patch(
    "/subject-attributes/{definition_id}", response_model=SubjectAttributeResponse
)
def patch_definition(
    definition_id: str,
    body: SubjectAttributePatchIn,
    caller: UserRecord = Depends(_WRITE),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> SubjectAttributeResponse:
    record = service.patch_definition(
        definition_id,
        **_sent(body),
        actor_user_id=caller.id,
        actor_token_id=actor_token_id,
    )
    return SubjectAttributeResponse(subject_attribute=_definition_out(record))


@router.delete(
    "/subject-attributes/{definition_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_definition(
    definition_id: str,
    caller: UserRecord = Depends(_WRITE),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> None:
    service.delete_definition(
        definition_id, actor_user_id=caller.id, actor_token_id=actor_token_id
    )
