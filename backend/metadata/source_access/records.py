"""Public Source Access values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

EVERY_SOURCE_TARGET = "*"
ACCESS_LEVELS: tuple[str, ...] = ("viewer", "steward", "maintainer")


@dataclass(frozen=True, slots=True)
class SourceIdSet:
    """Source ids on which a User holds a Permission.

    ``all_sources`` True means every Source, and ``source_ids`` is empty.
    An empty ``source_ids`` with ``all_sources`` False is not every Source.
    """

    all_sources: bool
    source_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class SourceMembership:
    id: str
    subject_type: str
    subject_id: str
    target: str
    level: str
    subject_name: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AccessContribution:
    kind: str
    subject_name: str
    level: str
    membership_id: str | None
    subject_type: str
    subject_id: str


@dataclass(frozen=True, slots=True)
class ExplainedSource:
    source_id: str
    level: str
    contributions: tuple[AccessContribution, ...]
