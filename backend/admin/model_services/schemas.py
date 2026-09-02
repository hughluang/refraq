"""Model Service HTTP schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from backend.core.pagination import OffsetPage
from backend.core.time import Instant

PurposeName = Literal["embedding"]
ProtocolName = Literal["openai_compat"]
RebuildChoice = Literal["none", "full"]
IndexStatus = Literal["none", "indexing", "ready", "failed"]


class ModelServiceCreateIn(BaseModel):
    purpose: PurposeName = "embedding"
    protocol: ProtocolName = "openai_compat"
    display_name: str = Field(min_length=1, max_length=128)
    url: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=256)
    api_key: str | None = Field(default=None, max_length=4096)


class ModelServicePatchIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    model: str | None = Field(default=None, min_length=1, max_length=256)
    protocol: ProtocolName | None = None
    api_key: str | None = Field(default=None, max_length=4096)
    clear_api_key: bool = False


class ModelServiceOpenIn(BaseModel):
    rebuild: RebuildChoice


class ModelServiceOut(BaseModel):
    id: str
    purpose: str
    protocol: str
    display_name: str
    url: str
    model: str
    has_secret: bool
    in_use: bool
    created_at: Instant
    updated_at: Instant


class PurposeStateOut(BaseModel):
    purpose: str
    closed: bool
    ready: bool
    in_use_id: str | None
    generation: int
    index_status: IndexStatus


class ModelServiceTestOut(BaseModel):
    ok: bool
    dimension: int
    elapsed_ms: int
    model: str


class ModelServiceSpecOut(BaseModel):
    purpose: str
    protocol: str
    spec: dict[str, object]


class ModelServiceList(OffsetPage[ModelServiceOut]):
    pass
