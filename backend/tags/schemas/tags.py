"""HTTP shapes for the Tag collection."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.core.pagination import OffsetPage
from backend.core.time import Instant


class TagOut(BaseModel):
    id: str
    name: str
    description: str | None = None
    created_at: Instant
    updated_at: Instant


class TagDetail(TagOut):
    entity_count: int
    channel_count: int


class TagResponse(BaseModel):
    tag: TagDetail


class TagListResponse(OffsetPage[TagOut]):
    pass


class TagCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None


class TagPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None


class EntitySubjectOut(BaseModel):
    kind: Literal["entity"]
    id: str
    name: str
    table_name: str
    deprecated_at: Instant | None = None
    ever_published: bool


class ChannelSubjectOut(BaseModel):
    kind: Literal["channel"]
    id: str
    name: str
    active: bool


TagSubjectOut = Annotated[
    EntitySubjectOut | ChannelSubjectOut, Field(discriminator="kind")
]


class TagSubjectListResponse(OffsetPage[TagSubjectOut]):
    pass
