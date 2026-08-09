"""Controlled query API schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "QueryRequest",
    "QueryResponse",
]


class QueryRequest(BaseModel):
    sql: str
    max_rows: int | None = Field(default=None, ge=1)


class QueryResponse(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool
    duration_ms: int
