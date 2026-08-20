"""Catalog record dataclasses and id helpers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Sentinel: field omitted from patch (distinct from explicit None).
UNSET: Any = object()


class CatalogWriteAborted(Exception):
    """Raised when fail-safe or incomplete collect prevents catalog mutation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class CatalogColumnRecord:
    id: str
    object_id: str
    locator_key: str
    name: str
    ordinal: int
    data_type: str
    nullable: bool
    is_present: bool
    default_value: str | None
    comment: str | None
    business_name: str | None
    business_description: str | None
    column_semantics: dict[str, Any] | None
    enum_catalog: list[dict[str, Any]] | None
    semantic_source: str | None
    field_kind: str
    created_at: datetime
    updated_at: datetime
    normalized_type: str | None = None


@dataclass
class CatalogForeignKeyRecord:
    name: str
    columns: list[str]
    ref_schema: str
    ref_table: str
    ref_columns: list[str]
    id: str | None = None
    is_present: bool = True


@dataclass
class CatalogIndexRecord:
    name: str
    columns: list[str]
    is_unique: bool
    id: str | None = None
    is_present: bool = True


@dataclass
class CatalogObjectRecord:
    id: str
    source_id: str
    locator_key: str
    object_type: str
    schema_name: str
    name: str
    ddl: str | None
    comment: str | None
    primary_key: list[str] | None
    is_present: bool
    business_name: str | None
    business_description: str | None
    object_category: str | None
    grain_description: str | None
    business_primary_key: list[str] | None
    business_domain_id: str | None
    evidence_summary: list[str] | None
    open_questions: list[str] | None
    semantic_source: str | None
    business_semantics_ready: bool
    semantics_updated_at: datetime | None
    last_structure_job_id: str | None
    collected_at: datetime | None
    created_at: datetime
    updated_at: datetime
    columns: list[CatalogColumnRecord] = field(default_factory=list)
    foreign_keys: list[CatalogForeignKeyRecord] = field(default_factory=list)
    indexes: list[CatalogIndexRecord] = field(default_factory=list)


@dataclass
class CatalogJoinRecord:
    id: str
    from_column_id: str
    to_column_id: str
    evidence: str
    join_kind: str
    join_expression: str | None
    created_by_user_id: str | None
    created_at: datetime
    rejected_at: datetime | None = None
    rejected_by_user_id: str | None = None

    @property
    def is_rejected(self) -> bool:
        return self.rejected_at is not None


def new_object_id() -> str:
    return f"obj_{uuid.uuid4().hex[:12]}"


def new_column_id() -> str:
    return f"col_{uuid.uuid4().hex[:12]}"


def new_join_id() -> str:
    return f"join_{uuid.uuid4().hex[:12]}"


def new_join_change_id() -> str:
    return f"jch_{uuid.uuid4().hex[:12]}"


def new_fk_id() -> str:
    return f"fk_{uuid.uuid4().hex[:12]}"


def new_index_id() -> str:
    return f"idx_{uuid.uuid4().hex[:12]}"


