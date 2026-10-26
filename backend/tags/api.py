"""Published Tag assignment surface.

Entity and Channel call these operations. A passed SQLAlchemy session joins the
caller's transaction and is not committed here. The memory store has no
transaction, so a caller that must undo a failed create does that itself.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from sqlalchemy.orm import Session

from backend.admin.audit import persist_audit_event
from backend.core.time import utc_now
from backend.tags.errors import (
    TagAssignmentConflict,
    TagLimitExceeded,
    TagNameConflict,
    TagNotFound,
)
from backend.tags.ids import new_tag_id
from backend.tags.names import enforce_tag_name
from backend.tags.records import TagRecord
from backend.tags.store import TagUnit, get_tag_store

__all__ = [
    "KIND_CHANNEL",
    "KIND_ENTITY",
    "TAG_LIMIT",
    "BulkAssignment",
    "SubjectTag",
    "SubjectTags",
    "add_tags",
    "bulk_add_tags",
    "bulk_remove_tags",
    "clear_assignment",
    "count_subjects",
    "list_subject_ids",
    "read_assignment",
    "remove_tags",
    "replace_assignment",
    "resolve_or_create",
]

KIND_ENTITY = "entity"
KIND_CHANNEL = "channel"
TAG_LIMIT = 10

_KINDS = frozenset({KIND_ENTITY, KIND_CHANNEL})


@dataclass(frozen=True, slots=True)
class SubjectTag:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class SubjectTags:
    tags: tuple[SubjectTag, ...]
    tag_revision: int


@dataclass(frozen=True, slots=True)
class BulkAssignment:
    id: str
    tags: tuple[SubjectTag, ...]
    tag_revision: int


@dataclass(frozen=True, slots=True)
class _Audit:
    resource_type: str
    resource_id: str
    action: str
    detail: dict[str, object]


_R = TypeVar("_R")


def read_assignment(kind: str, subject_id: str) -> SubjectTags:
    _require_kind(kind)
    return get_tag_store().run(
        lambda view: _ordered(view, *view.read_assignment(kind, subject_id))
    )


def count_subjects(tag_id: str) -> tuple[int, int]:
    return get_tag_store().run(lambda view: view.count_kinds(tag_id))


def list_subject_ids(*, kind: str, tag_ids: list[str]) -> list[str]:
    """Subject ids that carry any of the live Tag ids. An unknown id matches nothing."""

    _require_kind(kind)
    return get_tag_store().run(
        lambda view: view.subjects_with_any(kind, set(tag_ids))
    )


def resolve_or_create(
    name: str,
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
    session: Session | None = None,
) -> TagRecord:
    """Attach an existing Tag or create one. A folded name does not rename the stored Tag."""

    display, comparison = enforce_tag_name(name)

    def work(view: TagUnit) -> tuple[TagRecord, bool]:
        existing = view.get_by_key(comparison)
        if existing is not None:
            return existing, False
        try:
            created = view.insert_tag(_new_tag(display, comparison))
        except TagNameConflict:
            winner = view.get_by_key(comparison)
            if winner is None:
                raise
            return winner, False
        return created, True

    record, created = get_tag_store().run(work, session=session)
    if created:
        _emit(
            [
                _Audit(
                    resource_type="tag",
                    resource_id=record.id,
                    action="create",
                    detail={"name": record.name},
                )
            ],
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            session=session,
        )
    return record


def replace_assignment(
    *,
    kind: str,
    subject_id: str,
    base_revision: int,
    tag_ids: list[str],
    names: list[str],
    actor_user_id: str | None,
    actor_token_id: str | None,
    session: Session | None = None,
) -> SubjectTags:
    """Replace one subject's set. Inline names are created in the same unit of work."""

    _require_kind(kind)

    def work(view: TagUnit) -> tuple[SubjectTags, list[_Audit]]:
        view.lock_subject(kind, subject_id)
        current_ids, revision = view.read_assignment(kind, subject_id)
        if base_revision != revision:
            raise TagAssignmentConflict()
        resolved = _lock_known_ids(view, tag_ids)
        planned = _plan_names(view, names, resolved)
        if len(resolved) + len(planned) > TAG_LIMIT:
            raise TagLimitExceeded([{"kind": kind, "id": subject_id}])
        created, resolved = _insert_planned(view, planned, resolved)
        if resolved == current_ids:
            return _ordered(view, current_ids, revision), []
        new_revision = revision + 1
        view.write_assignment(kind, subject_id, resolved, new_revision)
        presented = _ordered(view, resolved, new_revision)
        events = [
            _Audit(
                resource_type="tag",
                resource_id=record.id,
                action="create",
                detail={"name": record.name},
            )
            for record in created
        ]
        events.append(
            _Audit(
                resource_type=kind,
                resource_id=subject_id,
                action="tags.replace",
                detail={"tag_ids": [tag.id for tag in presented.tags]},
            )
        )
        return presented, events

    return _commit(work, actor_user_id=actor_user_id, actor_token_id=actor_token_id, session=session)


def add_tags(
    *,
    kind: str,
    subject_id: str,
    tag_ids: list[str],
    actor_user_id: str | None,
    actor_token_id: str | None,
    session: Session | None = None,
) -> SubjectTags:
    """Insert Tag ids into one subject's set. Does not create Tags and does not take a revision."""

    _require_kind(kind)

    def work(view: TagUnit) -> tuple[SubjectTags, list[_Audit]]:
        view.lock_subject(kind, subject_id)
        current_ids, revision = view.read_assignment(kind, subject_id)
        incoming = _lock_known_ids(view, tag_ids)
        resulting = current_ids | incoming
        if len(resulting) > TAG_LIMIT:
            raise TagLimitExceeded([{"kind": kind, "id": subject_id}])
        if resulting == current_ids:
            return _ordered(view, current_ids, revision), []
        new_revision = revision + 1
        view.write_assignment(kind, subject_id, resulting, new_revision)
        presented = _ordered(view, resulting, new_revision)
        return presented, [
            _Audit(
                resource_type=kind,
                resource_id=subject_id,
                action="tags.add",
                detail={"tag_ids": [tag.id for tag in presented.tags]},
            )
        ]

    return _commit(work, actor_user_id=actor_user_id, actor_token_id=actor_token_id, session=session)


def remove_tags(
    *,
    kind: str,
    subject_id: str,
    tag_ids: list[str],
    actor_user_id: str | None,
    actor_token_id: str | None,
    session: Session | None = None,
) -> SubjectTags:
    """Drop named Tag ids. Ids the subject does not carry, including unknown ids, are ignored."""

    _require_kind(kind)

    def work(view: TagUnit) -> tuple[SubjectTags, list[_Audit]]:
        view.lock_subject(kind, subject_id)
        current_ids, revision = view.read_assignment(kind, subject_id)
        resulting = current_ids - set(tag_ids)
        if resulting == current_ids:
            return _ordered(view, current_ids, revision), []
        new_revision = revision + 1
        view.write_assignment(kind, subject_id, resulting, new_revision)
        presented = _ordered(view, resulting, new_revision)
        return presented, [
            _Audit(
                resource_type=kind,
                resource_id=subject_id,
                action="tags.remove",
                detail={"tag_ids": [tag.id for tag in presented.tags]},
            )
        ]

    return _commit(work, actor_user_id=actor_user_id, actor_token_id=actor_token_id, session=session)


def bulk_add_tags(
    *,
    kind: str,
    subject_ids: list[str],
    tag_ids: list[str],
    actor_user_id: str | None,
    actor_token_id: str | None,
    session: Session | None = None,
) -> list[BulkAssignment]:
    """Insert Tag ids into each set. One unit of work. Does not create Tags."""

    return _bulk_apply(
        kind=kind,
        subject_ids=subject_ids,
        tag_ids=tag_ids,
        adding=True,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        session=session,
    )


def bulk_remove_tags(
    *,
    kind: str,
    subject_ids: list[str],
    tag_ids: list[str],
    actor_user_id: str | None,
    actor_token_id: str | None,
    session: Session | None = None,
) -> list[BulkAssignment]:
    """Drop named Tag ids. Ids a subject does not carry, including unknown ids, are ignored."""

    return _bulk_apply(
        kind=kind,
        subject_ids=subject_ids,
        tag_ids=tag_ids,
        adding=False,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        session=session,
    )


def _bulk_apply(
    *,
    kind: str,
    subject_ids: list[str],
    tag_ids: list[str],
    adding: bool,
    actor_user_id: str | None,
    actor_token_id: str | None,
    session: Session | None,
) -> list[BulkAssignment]:
    _require_kind(kind)

    def work(view: TagUnit) -> tuple[list[BulkAssignment], list[_Audit]]:
        ordered: list[str] = []
        seen: set[str] = set()
        for subject_id in subject_ids:
            if subject_id in seen:
                continue
            seen.add(subject_id)
            ordered.append(subject_id)
        for subject_id in sorted(ordered):
            view.lock_subject(kind, subject_id)
        incoming = _lock_known_ids(view, tag_ids) if adding else set(tag_ids)
        planned: list[tuple[str, set[str], set[str], int]] = []
        exceeded: list[dict[str, str]] = []
        for subject_id in ordered:
            current_ids, revision = view.read_assignment(kind, subject_id)
            resulting = (current_ids | incoming) if adding else (current_ids - incoming)
            if len(resulting) > TAG_LIMIT:
                exceeded.append({"kind": kind, "id": subject_id})
            planned.append((subject_id, current_ids, resulting, revision))
        if exceeded:
            raise TagLimitExceeded(exceeded)
        results: list[BulkAssignment] = []
        events: list[_Audit] = []
        action = "tags.add" if adding else "tags.remove"
        for subject_id, current_ids, resulting, revision in planned:
            if resulting == current_ids:
                presented = _ordered(view, current_ids, revision)
            else:
                revision = revision + 1
                view.write_assignment(kind, subject_id, resulting, revision)
                presented = _ordered(view, resulting, revision)
                events.append(
                    _Audit(
                        resource_type=kind,
                        resource_id=subject_id,
                        action=action,
                        detail={"tag_ids": [tag.id for tag in presented.tags]},
                    )
                )
            results.append(
                BulkAssignment(
                    id=subject_id,
                    tags=presented.tags,
                    tag_revision=presented.tag_revision,
                )
            )
        return results, events

    return _commit(
        work,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        session=session,
    )


def clear_assignment(
    *,
    kind: str,
    subject_id: str,
    session: Session | None = None,
) -> None:
    """Drop one subject's assignments and revision. Writes no audit event."""

    _require_kind(kind)

    def work(view: TagUnit) -> None:
        view.lock_subject(kind, subject_id)
        view.clear_assignment(kind, subject_id)

    get_tag_store().run(work, session=session)


def _commit(
    work: Callable[[TagUnit], tuple[_R, list[_Audit]]],
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
    session: Session | None,
) -> _R:
    presented, events = get_tag_store().run(work, session=session)
    _emit(
        events,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        session=session,
    )
    return presented


def _emit(
    events: list[_Audit],
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
    session: Session | None,
) -> None:
    for event in events:
        persist_audit_event(
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            action=event.action,
            result="success",
            detail=dict(event.detail),
            session=session,
        )


def _require_kind(kind: str) -> None:
    if kind not in _KINDS:
        raise ValueError(f"unsupported tag subject kind: {kind}")


def _lock_known_ids(view: TagUnit, tag_ids: list[str]) -> set[str]:
    """Lock and require every id. Duplicates count once. Lock order is the id order."""

    resolved: set[str] = set()
    for tag_id in sorted(set(tag_ids)):
        if view.get_tag(tag_id, lock=True) is None:
            raise TagNotFound()
        resolved.add(tag_id)
    return resolved


def _plan_names(
    view: TagUnit,
    names: list[str],
    resolved: set[str],
) -> list[tuple[str, str]]:
    """Enforce every name, then attach Tags that already exist. Returns names still to create."""

    enforced = [enforce_tag_name(name) for name in names]
    planned: list[tuple[str, str]] = []
    seen_keys: set[str] = set()
    for display, comparison in enforced:
        if comparison in seen_keys:
            continue
        seen_keys.add(comparison)
        existing = view.get_by_key(comparison)
        if existing is not None:
            resolved.add(existing.id)
            continue
        planned.append((display, comparison))
    return planned


def _insert_planned(
    view: TagUnit,
    planned: list[tuple[str, str]],
    resolved: set[str],
) -> tuple[list[TagRecord], set[str]]:
    created: list[TagRecord] = []
    for display, comparison in planned:
        try:
            record = view.insert_tag(_new_tag(display, comparison))
        except TagNameConflict:
            winner = view.get_by_key(comparison)
            if winner is None:
                raise
            record = winner
        else:
            created.append(record)
        resolved.add(record.id)
    return created, resolved


def _new_tag(display: str, comparison: str) -> TagRecord:
    now = utc_now()
    return TagRecord(
        id=new_tag_id(),
        name=display,
        name_key=comparison,
        description=None,
        created_at=now,
        updated_at=now,
    )


def _ordered(view: TagUnit, tag_ids: set[str], revision: int) -> SubjectTags:
    records: list[TagRecord] = []
    for tag_id in tag_ids:
        record = view.get_tag(tag_id, lock=False)
        if record is not None:
            records.append(record)
    records.sort(key=lambda item: (item.name_key, item.id))
    return SubjectTags(
        tags=tuple(SubjectTag(id=item.id, name=item.name) for item in records),
        tag_revision=revision,
    )
