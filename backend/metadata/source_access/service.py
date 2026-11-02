"""Source Access resolution. Callers use this module and do not reimplement the ladder."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.admin.errors import AuthForbidden
from backend.admin.role_store import RoleRecord, get_role_store
from backend.admin.roles import SUPER_ADMIN_KEY
from backend.admin.roles import effective_permissions as role_effective_permissions
from backend.admin.subjects import (
    existing_group_ids,
    existing_user_ids,
    group_labels,
    user_group_ids,
    user_labels,
)
from backend.admin.user_store import get_user_store
from backend.core.time import utc_now
from backend.metadata.source_access.errors import (
    SourceMembershipLevelUnknown,
    SourceMembershipSubjectUnknown,
)
from backend.metadata.source_access.records import (
    ACCESS_LEVELS,
    EVERY_SOURCE_TARGET,
    AccessContribution,
    ExplainedSource,
    SourceIdSet,
    SourceMembership,
)
from backend.metadata.source_access.store import (
    StoredMembership,
    get_source_access_store,
)
from backend.metadata.sources.store import get_source_store

_VIEWER_KEYS = frozenset(
    {"sources:read", "metadata:read", "catalog:sample", "query:run"}
)
_STEWARD_KEYS = _VIEWER_KEYS | frozenset({"metadata:write"})
_MAINTAINER_KEYS = _STEWARD_KEYS | frozenset({"sources:write", "jobs:run"})
_LEVEL_KEYS: dict[str, frozenset[str]] = {
    "viewer": _VIEWER_KEYS,
    "steward": _STEWARD_KEYS,
    "maintainer": _MAINTAINER_KEYS,
}
_LADDER_KEYS = _MAINTAINER_KEYS
_RANK = {level: index for index, level in enumerate(ACCESS_LEVELS)}
_NO_SOURCES = SourceIdSet(all_sources=False, source_ids=frozenset())
_ALL_SOURCES = SourceIdSet(all_sources=True, source_ids=frozenset())


@dataclass(frozen=True, slots=True)
class _Actor:
    user_id: str | None
    role: RoleRecord | None
    group_ids: frozenset[str]


class _Subjects:
    """Subject names for one call. Not retained after the call returns.

    A missing name means the subject is gone. Foundation names are required,
    so each label map is the existence check.
    """

    def __init__(self, rows: list[StoredMembership]) -> None:
        user_ids = [row.subject_id for row in rows if row.subject_type == "user"]
        group_ids = [row.subject_id for row in rows if row.subject_type == "group"]
        self._user_names = {
            user_id: label.display_name
            for user_id, label in user_labels(user_ids).items()
        }
        self._group_names = dict(group_labels(group_ids))
        self._role_names: dict[str, str] = {}
        for role_id in {row.subject_id for row in rows if row.subject_type == "role"}:
            role = get_role_store().get_by_id(role_id)
            if role is not None:
                self._role_names[role_id] = role.name

    def name(self, subject_type: str, subject_id: str) -> str | None:
        if subject_type == "user":
            return self._user_names.get(subject_id)
        if subject_type == "group":
            return self._group_names.get(subject_id)
        if subject_type == "role":
            return self._role_names.get(subject_id)
        return None


def create_membership(
    *,
    subject_type: str,
    subject_id: str,
    target: str,
    level: str,
) -> SourceMembership:
    record = _new_record(subject_type, subject_id, target, level)
    return _present(get_source_access_store().insert(record))


def create_membership_on(
    session: Session | None,
    *,
    subject_type: str,
    subject_id: str,
    target: str,
    level: str,
) -> SourceMembership:
    record = _new_record(subject_type, subject_id, target, level)
    return _present(get_source_access_store().insert_on(session, record))


def change_level(membership_id: str, level: str) -> SourceMembership | None:
    _require_level(level)
    stored = get_source_access_store().update_level(membership_id, level, utc_now())
    if stored is None:
        return None
    return _present(stored)


def change_level_on(
    session: Session | None, membership_id: str, level: str
) -> SourceMembership | None:
    _require_level(level)
    stored = get_source_access_store().update_level_on(
        session, membership_id, level, utc_now()
    )
    if stored is None:
        return None
    return _present(stored)


def delete_membership(membership_id: str) -> bool:
    return get_source_access_store().delete(membership_id)


def delete_membership_on(session: Session | None, membership_id: str) -> bool:
    return get_source_access_store().delete_on(session, membership_id)


def delete_for_source(source_id: str) -> None:
    get_source_access_store().delete_for_source(source_id)


def delete_for_source_on(session: Session | None, source_id: str) -> None:
    get_source_access_store().delete_for_source_on(session, source_id)


def list_memberships(*, target: str | None = None) -> tuple[SourceMembership, ...]:
    rows = get_source_access_store().list_memberships()
    if target is not None:
        rows = [row for row in rows if row.target == target]
    subjects = _Subjects(rows)
    listed = [_to_public(row, subjects) for row in rows]
    listed.sort(key=lambda row: (row.target, row.subject_type, row.subject_id, row.id))
    return tuple(listed)


def allows(user_id: str, source_id: str, permission: str, *more_source_ids: str) -> bool:
    """Whether ``permission`` is held on every given Source.

    No level on any Source returns False so the caller can answer with that
    resource's existing not-found code. When every Source has a level and one
    lacks the key, raise AuthForbidden. Callers pass Source ids from records
    they already loaded.
    """
    hidden = False
    missing_key = False
    for current in (source_id, *more_source_ids):
        if effective_level(user_id, current) is None:
            hidden = True
            continue
        if permission not in effective_permissions(user_id, current):
            missing_key = True
    if hidden:
        return False
    if missing_key:
        raise AuthForbidden()
    return True


def effective_level(user_id: str, source_id: str) -> str | None:
    return _level(_actor(user_id), source_id)


def effective_permissions(user_id: str, source_id: str) -> frozenset[str]:
    actor = _actor(user_id)
    level = _level(actor, source_id)
    if level is None:
        return frozenset()
    return _LEVEL_KEYS[level] & _held(actor)


def source_ids_for(user_id: str, permission: str) -> SourceIdSet:
    if permission not in _LADDER_KEYS:
        return _NO_SOURCES
    actor = _actor(user_id)
    if actor.user_id is None or permission not in _held(actor):
        return _NO_SOURCES
    if _is_super(actor):
        return _ALL_SOURCES
    rows = get_source_access_store().list_memberships()
    subjects = _Subjects(rows)
    ids: set[str] = set()
    for row in rows:
        if _match_name(actor, row, subjects, None) is None:
            continue
        if permission not in _LEVEL_KEYS[row.level]:
            continue
        if row.target == EVERY_SOURCE_TARGET:
            return _ALL_SOURCES
        ids.add(row.target)
    return SourceIdSet(all_sources=False, source_ids=frozenset(ids))


def explain_user(user_id: str) -> tuple[ExplainedSource, ...]:
    actor = _actor(user_id)
    if actor.user_id is None:
        return ()
    rows = get_source_access_store().list_memberships()
    subjects = _Subjects(rows)
    sources, _total = get_source_store().list_sources(limit=None)
    explained: list[ExplainedSource] = []
    for source in sources:
        contributions = _contributions(actor, rows, subjects, source.id)
        if not contributions:
            continue
        explained.append(
            ExplainedSource(
                source_id=source.id,
                level=_max_level(item.level for item in contributions),
                contributions=tuple(contributions),
            )
        )
    explained.sort(key=lambda item: item.source_id)
    return tuple(explained)


def _new_record(
    subject_type: str, subject_id: str, target: str, level: str
) -> StoredMembership:
    _require_level(level)
    _require_subject(subject_type, subject_id)
    now = utc_now()
    return StoredMembership(
        id=f"smb_{uuid.uuid4().hex[:12]}",
        subject_type=subject_type,
        subject_id=subject_id,
        target=target,
        level=level,
        created_at=now,
        updated_at=now,
    )


def _require_level(level: str) -> None:
    if level not in _LEVEL_KEYS:
        raise SourceMembershipLevelUnknown()


def _require_subject(subject_type: str, subject_id: str) -> None:
    if subject_type == "user" and subject_id in existing_user_ids([subject_id]):
        return
    if subject_type == "role" and get_role_store().get_by_id(subject_id) is not None:
        return
    if subject_type == "group" and subject_id in existing_group_ids([subject_id]):
        return
    raise SourceMembershipSubjectUnknown()


def _actor(user_id: str) -> _Actor:
    user = get_user_store().get_by_id(user_id)
    if user is None:
        return _Actor(user_id=None, role=None, group_ids=frozenset())
    role = get_role_store().get_by_id(user.role_id) if user.role_id else None
    return _Actor(
        user_id=user.id,
        role=role,
        group_ids=frozenset(user_group_ids(user.id)),
    )


def _level(actor: _Actor, source_id: str) -> str | None:
    if actor.user_id is None:
        return None
    if _is_super(actor):
        return "maintainer"
    rows = get_source_access_store().list_memberships()
    subjects = _Subjects(rows)
    return _highest(
        row.level
        for row in rows
        if _match_name(actor, row, subjects, source_id) is not None
    )


def _is_super(actor: _Actor) -> bool:
    return actor.role is not None and actor.role.key == SUPER_ADMIN_KEY


def _held(actor: _Actor) -> frozenset[str]:
    if actor.role is None:
        return frozenset()
    return frozenset(role_effective_permissions(actor.role))


def _subject_matches(actor: _Actor, row: StoredMembership) -> bool:
    if actor.user_id is None:
        return False
    if row.subject_type == "user":
        return row.subject_id == actor.user_id
    if row.subject_type == "role":
        return actor.role is not None and row.subject_id == actor.role.id
    if row.subject_type == "group":
        return row.subject_id in actor.group_ids
    return False


def _match_name(
    actor: _Actor,
    row: StoredMembership,
    subjects: _Subjects,
    source_id: str | None,
) -> str | None:
    if not _subject_matches(actor, row):
        return None
    if source_id is not None and not (
        row.target == source_id or row.target == EVERY_SOURCE_TARGET
    ):
        return None
    return subjects.name(row.subject_type, row.subject_id)


def _max_level(levels: Iterable[str]) -> str:
    return max(levels, key=_RANK.__getitem__)


def _highest(levels: Iterable[str]) -> str | None:
    found = list(levels)
    if not found:
        return None
    return _max_level(found)


def _kind(row: StoredMembership) -> str:
    if row.target == EVERY_SOURCE_TARGET:
        return "every"
    if row.subject_type == "group":
        return "group"
    if row.subject_type == "role":
        return "role"
    return "direct"


def _contributions(
    actor: _Actor,
    rows: list[StoredMembership],
    subjects: _Subjects,
    source_id: str,
) -> list[AccessContribution]:
    contributions: list[AccessContribution] = []
    if _is_super(actor) and actor.role is not None:
        contributions.append(
            AccessContribution(
                kind="identity",
                subject_name=actor.role.name,
                level="maintainer",
                membership_id=None,
                subject_type="role",
                subject_id=actor.role.id,
            )
        )
    for row in rows:
        name = _match_name(actor, row, subjects, source_id)
        if name is None:
            continue
        contributions.append(
            AccessContribution(
                kind=_kind(row),
                subject_name=name,
                level=row.level,
                membership_id=row.id,
                subject_type=row.subject_type,
                subject_id=row.subject_id,
            )
        )
    return contributions


def _present(record: StoredMembership) -> SourceMembership:
    return _to_public(record, _Subjects([record]))


def _to_public(record: StoredMembership, subjects: _Subjects) -> SourceMembership:
    return SourceMembership(
        id=record.id,
        subject_type=record.subject_type,
        subject_id=record.subject_id,
        target=record.target,
        level=record.level,
        subject_name=subjects.name(record.subject_type, record.subject_id),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
