"""Controlled query and Catalog Sample API schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

__all__ = [
    "ColumnDeclaration",
    "QueryRequest",
    "QueryResponse",
    "SampleFilterIn",
    "SampleMatch",
    "SampleOrderIn",
    "SampleRequest",
    "SampleResponse",
]

SampleFilterOp = Literal[
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "between",
    "in",
    "not_in",
    "contains",
    "not_contains",
    "starts_with",
    "ends_with",
    "is_null",
    "is_not_null",
]
SampleMatch = Literal["all", "any"]
OrderDirection = Literal["asc", "desc"]


class QueryRequest(BaseModel):
    sql: str
    max_rows: int | None = Field(default=None, ge=1)


TemporalKind = Literal[
    "date",
    "time",
    "time_with_offset",
    "local_datetime",
    "timestamp_with_time_zone",
    "timestamp_with_local_time_zone",
    "interval",
    "interval_calendar",
    "interval_fixed",
]


class ColumnDeclaration(BaseModel):
    name: str
    temporal_kind: TemporalKind | None = None
    precision: int | None = None
    nullable: bool | None = None


class QueryResponse(BaseModel):
    columns: list[str]
    declarations: list[ColumnDeclaration]
    rows: list[list[Any]]
    truncated: bool
    duration_ms: int


class SampleFilterIn(BaseModel):
    column: str | None = None
    op: SampleFilterOp = "eq"
    value: str | list[str] | None = ""

    @field_validator("op", mode="before")
    @classmethod
    def _normalize_legacy_op(cls, raw: Any) -> Any:
        if raw == "neq":
            return "ne"
        return raw


class SampleOrderIn(BaseModel):
    column: str
    direction: OrderDirection = "asc"


class SampleRequest(BaseModel):
    columns: list[str] | None = None
    match: SampleMatch = "all"
    filters: list[SampleFilterIn] = Field(default_factory=list)
    order_by: list[SampleOrderIn] = Field(default_factory=list)
    offset: int = Field(default=0, ge=0)
    limit: int | None = Field(default=None, ge=1)
    include_sql: bool = False


class SampleResponse(BaseModel):
    columns: list[str]
    declarations: list[ColumnDeclaration]
    rows: list[list[Any]]
    truncated: bool
    duration_ms: int
    offset: int
    limit: int
    has_more: bool
    sql: str | None = None
