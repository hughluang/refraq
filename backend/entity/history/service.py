"""Published historical reads for one Business Entity.

``read_history`` is the interactive page. ``read_incremental`` is the
commit-order page the platform System Identity consumes. Both compile the
subject's current policy once and project stored images with that policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from backend.admin.subjects import user_group_ids
from backend.admin.user_store import UserRecord, ensure_system_user, get_user_store
from backend.core.time import format_instant
from backend.entity.access.compiler import compile_policy, subject_outcome
from backend.entity.access.errors import EntityAccessCombinationLimit
from backend.entity.access.facts import Person
from backend.entity.access.plan import load_head, load_policy
from backend.entity.access.service import _ensure_generated
from backend.entity.access.store import get_access_store
from backend.entity.change_log import (
    ChangeLogEntry,
    ChangeLogTable,
    read_change_log,
    read_effective,
    read_entries_after,
)
from backend.entity.changes import ChangeLogOff
from backend.entity.ddl import ENTITY_DATA_SCHEMA, qualified_table
from backend.entity.entity_db import get_entity_engine
from backend.entity.errors import EntityNotFound
from backend.entity.history.bounds import _blank, _bound, _occurred_to_bound
from backend.entity.history.project import SideWork, project_sides
from backend.entity.lifecycle import PUBLISHED
from backend.entity.service import change_log_tables
from backend.entity.store import get_entity_store
from backend.entity.table_name import compose_physical_table_name

__all__ = [
    "HistoryEvent",
    "HistoryPage",
    "HistorySide",
    "IncrementalEvent",
    "IncrementalPage",
    "IncrementalPosition",
    "read_history",
    "read_incremental",
]

SideState = Literal["absent", "unavailable", "visible"]


@dataclass(frozen=True, slots=True)
class HistorySide:
    """One side of a stored change.

    ``absent`` is not part of the operation. ``unavailable`` is not safely
    readable. Only ``visible`` carries ``values``.
    """

    state: SideState
    values: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class HistoryEvent:
    """One interactive event, newest sequence first. No physical table name."""

    sequence: int
    operation: str
    occurred_at: str
    source: str | None
    subject: str | None
    version_id: str
    version_number: int
    before: HistorySide
    after: HistorySide


@dataclass(frozen=True, slots=True)
class HistoryPage:
    """Visible events and the last candidate evaluated on this storage page.

    ``continuation`` is that candidate's sequence when another candidate may
    remain. It is absent only when this page did not fill the storage page.
    """

    events: list[HistoryEvent]
    continuation: int | None


@dataclass(frozen=True, slots=True)
class IncrementalPosition:
    """Last stored event fully evaluated. ``commit_seq`` is the resume bound."""

    commit_seq: int
    seq: int


@dataclass(frozen=True, slots=True)
class IncrementalEvent:
    """One eligible consumption event, in commit order.

    ``physical_table`` stays so a later consumer can group the stored version.
    """

    sequence: int
    commit_seq: int
    operation: str
    occurred_at: str
    source: str | None
    subject: str | None
    physical_table: str
    version_id: str
    version_number: int
    before: HistorySide
    after: HistorySide


@dataclass(frozen=True, slots=True)
class IncrementalPage:
    """Eligible events, the scan position, and whether stored candidates remain.

    ``progress`` is empty when the scan saw no stored event. ``has_more`` follows
    the stored candidate range, not the visible event count.
    """

    events: list[IncrementalEvent]
    progress: IncrementalPosition | None
    has_more: bool


def read_history(
    entity_id: str,
    user: UserRecord,
    *,
    before_sequence: int | None = None,
    operation: str | None = None,
    source: str | None = None,
    subject: str | None = None,
    row_identity: str | None = None,
    occurred_from: str | None = None,
    occurred_to: str | None = None,
) -> HistoryPage:
    """One interactive page for an already resolved subject.

    Filters match the change-log list, including a fraction-less ``occurred_to``
    that covers the rest of that second. ``row_identity`` is only the existing
    raw candidate predicate. An update whose two visible projections are equal
    is omitted. The continuation is the last candidate evaluated on the storage
    page, including a candidate omitted from ``events``.
    """
    policy, outcome, person, head_attributes = _authorize(entity_id, user)
    index = _versions(entity_id)
    with get_entity_engine().begin() as conn:
        page = read_change_log(
            conn,
            entity_id,
            [item.table for item in index.values()],
            before_sequence=before_sequence,
            operation=operation,
            source=source,
            subject=_blank(subject),
            row_identity=_blank(row_identity),
            occurred_from=_bound(occurred_from),
            occurred_to=_occurred_to_bound(occurred_to),
        )
        projected = _project(
            conn, page.items, index, policy, outcome, person, head_attributes
        )
    events = [
        HistoryEvent(
            sequence=entry.sequence,
            operation=entry.operation,
            occurred_at=format_instant(entry.occurred_at),
            source=entry.source,
            subject=entry.subject,
            version_id=version_id,
            version_number=version_number,
            before=before,
            after=after,
        )
        for entry, version_id, version_number, before, after in projected
        if _eligible(before, after) and not _same_update(entry.operation, before, after)
    ]
    return HistoryPage(events=events, continuation=page.next_before_sequence)


def read_incremental(
    entity_id: str,
    *,
    after: IncrementalPosition | None,
    bound: int,
    limit: int,
) -> IncrementalPage:
    """One commit-order page as the platform System Identity.

    ``limit`` is the candidate count, not a visible-event count. Equal projected
    updates stay. An event with no visible side is omitted and still advances
    ``progress``. Recording off raises ``ChangeLogOff``.
    """
    user = ensure_system_user(get_user_store())
    policy, outcome, person, head_attributes = _authorize(entity_id, user)
    index = _versions(entity_id)
    with get_entity_engine().begin() as conn:
        effective = read_effective(conn, entity_id)
        if effective is None or not effective.recording:
            raise ChangeLogOff()
        spans, has_more = read_entries_after(
            conn,
            entity_id,
            [item.table for item in index.values()],
            after_commit=None if after is None else after.commit_seq,
            bound_commit=bound,
            limit=limit,
        )
        entries = [entry for entry, _commit in spans]
        projected = _project(
            conn, entries, index, policy, outcome, person, head_attributes
        )
    events: list[IncrementalEvent] = []
    for (_entry, commit), (entry, version_id, version_number, before, after_side) in zip(
        spans, projected, strict=True
    ):
        if not _eligible(before, after_side):
            continue
        events.append(
            IncrementalEvent(
                sequence=entry.sequence,
                commit_seq=commit,
                operation=entry.operation,
                occurred_at=format_instant(entry.occurred_at),
                source=entry.source,
                subject=entry.subject,
                physical_table=entry.physical_table,
                version_id=version_id,
                version_number=version_number,
                before=before,
                after=after_side,
            )
        )
    progress = None
    if spans:
        last, last_commit = spans[-1]
        progress = IncrementalPosition(commit_seq=last_commit, seq=last.sequence)
    return IncrementalPage(events=events, progress=progress, has_more=has_more)


@dataclass(frozen=True, slots=True)
class _Version:
    version_id: str
    version_number: int
    table: ChangeLogTable


def _authorize(
    entity_id: str, user: UserRecord
) -> tuple[Any, Any, Person, tuple[Any, ...]]:
    head = load_head(entity_id)
    revision = get_access_store().revision(entity_id)
    person = Person(
        user_id=user.id,
        role_id=user.role_id,
        group_ids=user_group_ids(user.id),
    )
    policy = load_policy(head, revision, people=(person,))
    compiled = compile_policy(policy)
    outcome = subject_outcome(
        compiled, policy, person, action="read", narrow=None
    )
    if outcome.over_limit:
        raise EntityAccessCombinationLimit(
            "access configuration over limit for this subject"
        )
    if outcome.hidden or not outcome.grant_ids or outcome.shape is None:
        raise EntityNotFound()
    _ensure_generated(head, outcome, revision, user_id=user.id)
    return policy, outcome, person, head.attributes


def _versions(entity_id: str) -> dict[str, _Version]:
    tables = {item.physical_table: item for item in change_log_tables(entity_id)}
    entity = get_entity_store().get_entity(entity_id)
    if entity is None:
        raise EntityNotFound()
    found: dict[str, _Version] = {}
    for version in get_entity_store().list_all_versions(entity_id):
        if version.publish_status != PUBLISHED:
            continue
        name, _comment = compose_physical_table_name(
            entity.table_name, version.version, version.id
        )
        physical = qualified_table(ENTITY_DATA_SCHEMA, name)
        table = tables.get(physical)
        if table is None:
            continue
        found[physical] = _Version(
            version_id=version.id,
            version_number=version.version,
            table=table,
        )
    return found


def _project(
    conn: Any,
    entries: list[ChangeLogEntry],
    index: dict[str, _Version],
    policy: Any,
    outcome: Any,
    person: Person,
    head_attributes: tuple[Any, ...],
) -> list[tuple[ChangeLogEntry, str, int, HistorySide, HistorySide]]:
    works: list[SideWork] = []
    located: list[tuple[ChangeLogEntry, _Version]] = []
    for entry in entries:
        version = index[entry.physical_table]
        located.append((entry, version))
        snapshots = version.table.reference_snapshots
        works.append(
            SideWork(
                key=_key(entry, "before"),
                image=entry.before,
                attributes=version.table.attributes,
                reference_snapshots=snapshots,
            )
        )
        works.append(
            SideWork(
                key=_key(entry, "after"),
                image=entry.after,
                attributes=version.table.attributes,
                reference_snapshots=snapshots,
            )
        )
    projected = project_sides(
        conn, works, policy, outcome, person, head_attributes
    )
    return [
        (
            entry,
            version.version_id,
            version.version_number,
            _as_side(projected[_key(entry, "before")]),
            _as_side(projected[_key(entry, "after")]),
        )
        for entry, version in located
    ]


def _as_side(projected: tuple[str, dict[str, Any] | None]) -> HistorySide:
    state, values = projected
    if state == "visible":
        return HistorySide(state="visible", values=values)
    if state == "absent":
        return HistorySide(state="absent")
    return HistorySide(state="unavailable")


def _key(entry: ChangeLogEntry, side: str) -> str:
    return f"{entry.sequence}:{side}"


def _eligible(before: HistorySide, after: HistorySide) -> bool:
    return before.state == "visible" or after.state == "visible"


def _same_update(operation: str, before: HistorySide, after: HistorySide) -> bool:
    return (
        operation == "update"
        and before.state == "visible"
        and after.state == "visible"
        and before.values == after.values
    )
