"""User Group and Subject Attribute records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

__all__ = [
    "KEY_MAX_LENGTH",
    "NAME_MAX_LENGTH",
    "STRING_VALUE_MAX_LENGTH",
    "SUBJECT_TYPES",
    "VALUES_MAX",
    "VALUE_TYPES",
    "SubjectAttributeRecord",
    "SubjectType",
    "SubjectValue",
    "UserGroupRecord",
    "UserLabel",
    "ValueType",
]

ValueType = Literal["string", "integer", "date", "dictionary", "user"]
SubjectType = Literal["user", "group"]
SubjectValue = str | int

VALUE_TYPES: tuple[ValueType, ...] = ("string", "integer", "date", "dictionary", "user")
SUBJECT_TYPES: tuple[SubjectType, ...] = ("user", "group")
KEY_MAX_LENGTH = 63
NAME_MAX_LENGTH = 256
STRING_VALUE_MAX_LENGTH = 256
VALUES_MAX = 256


@dataclass(frozen=True, slots=True)
class UserGroupRecord:
    id: str
    key: str
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SubjectAttributeRecord:
    id: str
    key: str
    name: str
    description: str | None
    value_type: ValueType
    dictionary_id: str | None
    multi_value: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class UserLabel:
    account: str
    display_name: str
