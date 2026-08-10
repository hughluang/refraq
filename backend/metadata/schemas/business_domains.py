"""Business Domain HTTP schemas."""

from __future__ import annotations

from datetime import datetime

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
    created_at: datetime
    updated_at: datetime


class BusinessDomainListResponse(BaseModel):
    items: list[BusinessDomainOut]
    total: int = 0
    limit: int = 100
    offset: int = 0


class BusinessDomainResponse(BaseModel):
    domain: BusinessDomainOut


class BusinessDomainCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    description: str | None = None


class BusinessDomainPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = None
