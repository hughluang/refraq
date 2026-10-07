"""User Group and Subject Attribute HTTP shapes (docs/api-contracts-users.md §8–§9)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from backend.admin.schemas.user import UserSummary
from backend.core.pagination import OffsetPage
from backend.core.time import Instant

SubjectValues = dict[str, list[str | int]]


class UserGroupOut(BaseModel):
    id: str
    key: str
    name: str
    description: str | None
    member_count: int
    created_at: Instant
    updated_at: Instant


class UserGroupList(OffsetPage[UserGroupOut]):
    pass


class UserGroupResponse(BaseModel):
    group: UserGroupOut


class UserGroupsResponse(BaseModel):
    groups: list[UserGroupOut]


class UserGroupCreateIn(BaseModel):
    key: Any = None
    name: Any = None
    description: Any = None


class UserGroupPatchIn(BaseModel):
    key: Any = None
    name: Any = None
    description: Any = None


class UserGroupMembersList(OffsetPage[UserSummary]):
    pass


class UserGroupsReplaceIn(BaseModel):
    group_ids: list[str]


class SubjectAttributeOut(BaseModel):
    id: str
    key: str
    name: str
    description: str | None
    value_type: str
    dictionary_id: str | None
    multi_value: bool
    created_at: Instant
    updated_at: Instant


class SubjectAttributeList(OffsetPage[SubjectAttributeOut]):
    pass


class SubjectAttributeResponse(BaseModel):
    subject_attribute: SubjectAttributeOut


class SubjectAttributeCreateIn(BaseModel):
    key: Any = None
    name: Any = None
    description: Any = None
    value_type: Any = None
    dictionary_id: Any = None
    multi_value: Any = False


class SubjectAttributePatchIn(BaseModel):
    key: Any = None
    value_type: Any = None
    dictionary_id: Any = None
    name: Any = None
    description: Any = None
    multi_value: Any = None


class SubjectValuesIn(BaseModel):
    values: Any = None


class SubjectValuesResponse(BaseModel):
    values: SubjectValues


class UserSubjectValuesResponse(BaseModel):
    values: SubjectValues
    effective: SubjectValues
