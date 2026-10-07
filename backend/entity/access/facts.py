"""Shared policy facts for the row-rule language and the compiler."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from backend.entity.attribute_type import resolve

__all__ = [
    "ACTIONS",
    "AttrFact",
    "GrantSpec",
    "Level",
    "Narrow",
    "Person",
    "ProfileSpec",
    "RestrictionSpec",
    "SubjectAttrFact",
]

Action = Literal["read", "write", "export", "mcp_query"]
ACTIONS: tuple[Action, ...] = ("read", "write", "export", "mcp_query")
SubjectKind = Literal["user", "role", "group"]


@dataclass(frozen=True, slots=True)
class AttrFact:
    attribute_id: str
    name: str
    type: str
    dictionary_id: str | None = None
    max_length: int | None = None
    precision: int | None = None
    scale: int | None = None
    codes: tuple[str, ...] | None = None
    reference_key_type: str | None = None
    reference_max_length: int | None = None

    def value_type(self) -> str:
        if self.type == "reference":
            return self.reference_key_type or ""
        return self.type

    def operators(self) -> tuple[str, ...]:
        kind = self.value_type()
        if not kind:
            return ()
        return resolve(kind).operators

    def pg_type(self) -> str:
        kind = self.value_type()
        return _PG_TYPE.get(kind, "text")


_PG_TYPE = {
    "string": "text",
    "text": "text",
    "integer": "bigint",
    "decimal": "numeric",
    "number": "double precision",
    "boolean": "boolean",
    "date": "date",
    "timestamp": "timestamptz",
    "time": "time",
    "json": "jsonb",
    "dictionary": "text",
    "user": "text",
}


@dataclass(frozen=True, slots=True)
class SubjectAttrFact:
    key: str
    value_type: str
    dictionary_id: str | None
    multi_value: bool


@dataclass(frozen=True, slots=True)
class Level:
    key: str
    mode: str | dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProfileSpec:
    id: str
    key: str
    columns: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class GrantSpec:
    id: str
    subject_type: SubjectKind
    subject_id: str
    profile_id: str
    row_rule: dict[str, Any] | None
    actions: frozenset[str]
    status: str
    valid_until: datetime | None


@dataclass(frozen=True, slots=True)
class RestrictionSpec:
    id: str
    mode: Literal["all", "only", "except"]
    subjects: tuple[tuple[str, str], ...]
    row_rule: dict[str, Any] | None
    deny_columns: tuple[str, ...]
    ceilings: tuple[tuple[str, str], ...]
    actions: frozenset[str]


@dataclass(frozen=True, slots=True)
class Person:
    user_id: str
    role_id: str | None
    group_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Narrow:
    kind: Literal["user", "role", "group"]
    id: str | None = None
