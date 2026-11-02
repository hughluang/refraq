"""HTTP shapes for Source Membership management."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backend.core.time import Instant


class MembershipSubjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1)
    id: str = Field(min_length=1)


class MembershipCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: MembershipSubjectIn
    level: str = Field(min_length=1)


class MembershipLevelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: str = Field(min_length=1)


class MembershipSubjectOut(BaseModel):
    type: str
    id: str
    display_name: str | None
    missing: bool


class MembershipOut(BaseModel):
    id: str
    subject: MembershipSubjectOut
    target: str
    level: str
    created_at: Instant
    updated_at: Instant


class MembershipResponse(BaseModel):
    membership: MembershipOut


class MembershipListResponse(BaseModel):
    items: list[MembershipOut]
