"""Stored access-policy records. Persistence only; brokenness is derived."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

__all__ = [
    "AccessLogRecord",
    "BindingRecord",
    "GrantRecord",
    "LadderRecord",
    "ProfileRecord",
    "RestrictionRecord",
]


@dataclass
class LadderRecord:
    entity_id: str
    attribute_id: str
    levels: list[dict[str, Any]]
    updated_at: datetime


@dataclass
class ProfileRecord:
    id: str
    entity_id: str
    key: str
    name: str
    description: str | None
    columns: list[dict[str, str]]
    created_at: datetime
    updated_at: datetime


@dataclass
class GrantRecord:
    id: str
    entity_id: str
    subject_type: str
    subject_id: str
    profile_id: str
    row_rule: dict[str, Any] | None
    actions: list[str]
    status: str
    valid_until: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass
class RestrictionRecord:
    id: str
    entity_id: str
    applies_to: dict[str, Any]
    row_rule: dict[str, Any] | None
    deny_columns: list[str]
    ceilings: list[dict[str, str]]
    actions: list[str]
    created_at: datetime
    updated_at: datetime


@dataclass
class BindingRecord:
    entity_id: str
    head_version_id: str
    policy_revision: int
    combo_key: str
    shape_key: str
    action: str
    view_name: str
    columns: list[dict[str, Any]]
    ddl_sha256: str
    status: str
    sql: str


@dataclass
class AccessLogRecord:
    id: str
    created_at: datetime
    user_id: str
    pat_id: str | None
    request_id: str | None
    entity_id: str
    verb: str
    effective_grant_ids: list[str]
    narrowing: dict[str, Any] | None
    view_name: str | None
    policy_revision: int
    row_count: int | None
    outcome_code: str
    preview_subject_user_id: str | None
    duration_ms: int | None = None
