"""Console navigation response schemas."""

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
