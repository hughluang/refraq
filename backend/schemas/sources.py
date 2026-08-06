"""Pydantic schemas for Source and Connection APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SourceOut(BaseModel):
    id: str
    key: str
    name: str
    kind: str
    status: str
    description: str | None
    database_name: str | None
    schema_filter: str | None


class SourceListResponse(BaseModel):
    items: list[SourceOut]


class SourceResponse(BaseModel):
    source: SourceOut


class CreateSourceRequest(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    kind: Literal["database"] = "database"
    description: str | None = None
    database_name: str = Field(min_length=1, max_length=256)
    schema_filter: str | None = None


class PatchSourceRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = None
    status: Literal["active", "disabled"] | None = None
    database_name: str | None = Field(default=None, min_length=1, max_length=256)
    schema_filter: str | None = None


class ConnectionSecretIn(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class ConnectionOut(BaseModel):
    id: str
    source_id: str
    name: str
    engine: str
    host: str
    port: int
    status: str
    has_secret: bool
    secret_updated_at: datetime | None


class ConnectionListResponse(BaseModel):
    items: list[ConnectionOut]


class ConnectionResponse(BaseModel):
    connection: ConnectionOut


class CreateConnectionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    engine: Literal["postgresql", "mssql", "oracle"]
    host: str = Field(min_length=1, max_length=512)
    port: int = Field(ge=1, le=65535)
    secret: ConnectionSecretIn


class PatchConnectionRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    engine: Literal["postgresql", "mssql", "oracle"] | None = None
    host: str | None = Field(default=None, min_length=1, max_length=512)
    port: int | None = Field(default=None, ge=1, le=65535)
    status: Literal["active", "disabled"] | None = None


class PutConnectionSecretRequest(BaseModel):
    secret: ConnectionSecretIn
