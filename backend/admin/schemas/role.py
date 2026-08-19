"""Role and permission catalog schemas for the Management Foundation."""

from __future__ import annotations

from backend.core.pagination import OffsetPage
from pydantic import BaseModel, Field


class PermissionCatalogEntry(BaseModel):
    key: str
    description: str


class PermissionCatalogResponse(BaseModel):
    items: list[PermissionCatalogEntry]


class RoleSummary(BaseModel):
    id: str
    key: str
    name: str
    permissions: list[str]
    locked: bool
    user_count: int


class RoleListResponse(OffsetPage[RoleSummary]):
    pass


class RoleResponse(BaseModel):
    role: RoleSummary


class CreateRoleRequest(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    permissions: list[str] = Field(default_factory=list)


class UpdateRoleRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    permissions: list[str] | None = None
