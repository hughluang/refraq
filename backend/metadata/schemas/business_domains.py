"""Business Domain HTTP schemas."""

from __future__ import annotations


from backend.core.pagination import OffsetPage
from backend.core.time import Instant
from pydantic import BaseModel, Field

__all__ = [
    "BusinessDomainCreateRequest",
    "BusinessDomainListResponse",
    "BusinessDomainOut",
    "BusinessDomainPatchRequest",
    "BusinessDomainResponse",
]


class BusinessDomainOut(BaseModel):
    id: str
    code: str
    name: str
    description: str | None = None
    created_at: Instant
    updated_at: Instant


class BusinessDomainListResponse(OffsetPage[BusinessDomainOut]):
    pass


class BusinessDomainResponse(BaseModel):
    domain: BusinessDomainOut


class BusinessDomainCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    description: str | None = None


class BusinessDomainPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = None
