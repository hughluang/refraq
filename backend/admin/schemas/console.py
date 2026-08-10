"""Console navigation and module-identity response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class NavigationModuleResponse(BaseModel):
    id: str
    label_key: str
    route: str


class NavigationGroupResponse(BaseModel):
    id: str
    label_key: str
    modules: list[NavigationModuleResponse] = Field(default_factory=list)


class NavigationResponse(BaseModel):
    groups: list[NavigationGroupResponse] = Field(default_factory=list)


class ModuleRoutesResponse(BaseModel):
    list: str | None = None
    create: str | None = None
    edit: str | None = None
    show: str | None = None


class ModuleActionsResponse(BaseModel):
    list: str
    create: str | None = None
    edit: str | None = None
    delete: str | None = None
    show: str | None = None


class ModuleIdentityResponse(BaseModel):
    id: str
    label_key: str
    routes: ModuleRoutesResponse
    actions: ModuleActionsResponse


class ModuleIdentitiesResponse(BaseModel):
    modules: list[ModuleIdentityResponse] = Field(default_factory=list)
