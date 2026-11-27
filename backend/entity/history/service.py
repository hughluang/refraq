"""Published historical reads for one Business Entity.

``read_history`` is the interactive page. ``read_incremental`` is the
commit-order page the platform System Identity consumes.
``materialize_incremental_dataset`` lands commit-order pages directly into a
``channel_dataset`` table on one entity-database connection, re-evaluating
System Identity policy per page.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from backend.admin.subjects import user_group_ids
from backend.admin.user_store import UserRecord, ensure_system_user, get_user_store
from backend.core.time import format_instant
from backend.entity.access.compiler import compile_decisions, subject_outcome
from backend.entity.access.errors import EntityAccessCombinationLimit
from backend.entity.access.facts import Person
from backend.entity.access.masks import CLEAR
from backend.entity.access.plan import load_head, load_policy
from backend.entity.access.service import _ensure_generated
from backend.entity.access.store import get_access_store
from backend.entity.change_log import (
    ChangeLogEntry,
    read_change_log,
    read_effective,
)
from backend.entity.changes import ChangeLogOff
from backend.entity.data.sql import set_write_timeouts
from backend.entity.datasets import (
    analyze_on,
    copy_rows_on,
    create_table_on,
    relation_size_on,
)
from backend.entity.entity_db import get_entity_engine
from backend.entity.errors import (
    EntityChangeLogQueryUnsupported,
    EntityNotFound,
    EntityNotServing,
)
from backend.entity.history.bounds import _blank, _bound, _occurred_to_bound
from backend.entity.history.cursor import HistoryLookup, resolve_history_lookup
from backend.entity.history.incremental import (
    CHANGES_DATASET_COLUMNS,
    DATASET_COLUMN_PG_TYPES,
    ChangesDatasetColumn,
    IncrementalEvent,
    VersionMeta,
    compile_incremental_plan,
    execute_nosides_dataset_page,
    execute_with_sides_page,
    format_dataset_rows,
    normalize_dataset_columns,
)
from backend.entity.history.project import HistorySide, SideWork, project_sides
from backend.entity.reference_binding import frozen_reference_bindings_cover
from backend.entity.service import change_log_tables

__all__ = [
    "CHANGES_DATASET_COLUMNS",
    "ChangesDatasetColumn",
    "HistoryEvent",
    "HistoryPage",
    "HistorySide",
    "IncrementalDatasetResult",
    "IncrementalEvent",
    "IncrementalPage",
    "IncrementalPosition",
    "clear_cell",
    "materialize_incremental_dataset",
    "normalize_dataset_columns",
    "read_history",
    "read_incremental",
]

_INCREMENTAL_BATCH_SIZE = 10_000
_SERVING_HEAD_PREDATES = (
    "Serving head predates reference snapshots; publish a new version"
)


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
class IncrementalPage:
    """Eligible events, the scan position, and whether stored candidates remain.

    ``progress`` is empty when the scan saw no stored event. ``has_more`` follows
    the stored candidate range, not the visible event count.
    """

    events: list[IncrementalEvent]
    progress: IncrementalPosition | None
    has_more: bool


@dataclass(frozen=True, slots=True)
class IncrementalDatasetResult:
    """Materialized row count, storage size, scan position, and overflow flag."""

    row_count: int
    size_bytes: int
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
    version_id: str | None = None,
    row_id: str | None = None,
    occurred_from: str | None = None,
    occurred_to: str | None = None,
) -> HistoryPage:
    """One interactive page for an already resolved subject.

    Filters match the change-log list, including a fraction-less ``occurred_to``
    that covers the rest of that second. ``row_identity`` is business-key text.
    ``version_id`` and ``row_id`` together name one row of one logical version.
    A hit is an exact comparison on a visible side after projection. An event
    whose two visible projections are equal is omitted. The continuation is the
    last candidate evaluated on the storage page, including a candidate omitted
    from ``events``.
    """
    lookup = resolve_history_lookup(row_identity, version_id, row_id)
    policy, outcome, person = _authorize(entity_id, user)
    index = _versions(entity_id)
    if lookup.row_identity is not None and not _key_can_be_clear(index, outcome):
        raise EntityChangeLogQueryUnsupported()
    version_row = _version_row(index, lookup)
    if lookup.row_id is not None and version_row is None:
        return HistoryPage(events=[], continuation=None)
    with get_entity_engine().begin() as conn:
        page = read_change_log(
            conn,
            entity_id,
            [item.table for item in index.values()],
            before_sequence=before_sequence,
            operation=operation,
            source=source,
            subject=_blank(subject),
            key_query=lookup.row_identity,
            version_row=version_row,
            occurred_from=_bound(occurred_from),
            occurred_to=_occurred_to_bound(occurred_to),
        )
        projected = _project(conn, page.items, index, policy, outcome, person)
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
        if _eligible(before, after)
        and not _same_projection(before, after)
        and _lookup_hit(
            index[entry.physical_table],
            before,
            after,
            lookup,
            policy,
        )
    ]
    return HistoryPage(events=events, continuation=page.next_before_sequence)


def read_incremental(
    entity_id: str,
    *,
    after: IncrementalPosition | None,
    bound: int,
    limit: int,
    sources: Collection[str] | None = None,
) -> IncrementalPage:
    """Commit-order page as the platform System Identity under one policy snapshot.

    ``limit`` is the candidate count, not a visible-event count. Equal projected
    updates stay. An event with no visible side is omitted and still advances
    ``progress``. Recording off raises ``ChangeLogOff``. Large limits stream in
    bounded internal SQL batches under the single call-start policy.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    user = ensure_system_user(get_user_store())
    policy, outcome, person = _authorize(entity_id, user)
    index = _versions(entity_id)
    plan = compile_incremental_plan(
        policy=policy,
        outcome=outcome,
        person=person,
        versions=index,
    )
    events: list[IncrementalEvent] = []
    progress: IncrementalPosition | None = None
    has_more = False
    scanned = 0
    cursor_commit = None if after is None else after.commit_seq
    with get_entity_engine().begin() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        effective = read_effective(conn, entity_id)
        if effective is None or not effective.recording:
            raise ChangeLogOff()
        while scanned < limit:
            batch_limit = min(_INCREMENTAL_BATCH_SIZE, limit - scanned)
            summary, raw_events = execute_with_sides_page(
                conn,
                plan,
                entity_id=entity_id,
                after_commit=cursor_commit,
                bound_commit=bound,
                page_limit=batch_limit,
                sources=sources,
            )
            if summary.scanned_count == 0:
                has_more = False
                break
            assert summary.last_commit_seq is not None
            assert summary.last_seq is not None
            events.extend(raw_events)
            progress = IncrementalPosition(
                commit_seq=summary.last_commit_seq,
                seq=summary.last_seq,
            )
            cursor_commit = summary.last_commit_seq
            scanned += summary.scanned_count
            has_more = summary.has_more
            if not summary.has_more:
                break
    return IncrementalPage(events=events, progress=progress, has_more=has_more)


def materialize_incremental_dataset(
    entity_id: str,
    relation: str,
    *,
    after: IncrementalPosition | None,
    bound: int,
    limit: int,
    columns: Sequence[str] | None = None,
    sources: Collection[str] | None = None,
    page_size: int = _INCREMENTAL_BATCH_SIZE,
    before_page: Callable[[], int | None] | None = None,
    on_page_size: Callable[[int], None] | None = None,
) -> IncrementalDatasetResult:
    """Materialize bounded incremental Change Log rows into ``relation``.

    Resolves the platform System Identity access policy at the start of every
    page. When ``before`` and ``after`` are omitted from ``columns``, each page
    executes entirely inside PostgreSQL via ``INSERT INTO ... SELECT ...``.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if page_size < 1:
        raise ValueError("page_size must be at least 1")
    selected = normalize_dataset_columns(columns)
    pg_columns = [(col, DATASET_COLUMN_PG_TYPES[col]) for col in selected]

    row_count = 0
    scanned = 0
    progress: IncrementalPosition | None = None
    has_more = False
    cursor_commit = None if after is None else after.commit_seq

    with get_entity_engine().begin() as conn:
        if before_page is not None:
            rem_ms = before_page()
            if rem_ms is not None:
                set_write_timeouts(conn, max(1, int(rem_ms)))
        copy_columns = create_table_on(conn, relation, pg_columns)

        while scanned < limit:
            if scanned > 0 and before_page is not None:
                rem_ms = before_page()
                if rem_ms is not None:
                    set_write_timeouts(conn, max(1, int(rem_ms)))

            user = ensure_system_user(get_user_store())
            policy, outcome, person = _authorize(entity_id, user)
            index = _versions(entity_id)
            effective = read_effective(conn, entity_id)
            if effective is None or not effective.recording:
                raise ChangeLogOff()

            plan = compile_incremental_plan(
                policy=policy,
                outcome=outcome,
                person=person,
                versions=index,
                columns=selected,
            )
            batch_limit = min(page_size, limit - scanned)
            if not plan.want_sides:
                summary, inserted = execute_nosides_dataset_page(
                    conn,
                    plan,
                    entity_id=entity_id,
                    relation=relation,
                    after_commit=cursor_commit,
                    bound_commit=bound,
                    page_limit=batch_limit,
                    base_ord=row_count,
                    sources=sources,
                )
                row_count += inserted
            else:
                summary, raw_events = execute_with_sides_page(
                    conn,
                    plan,
                    entity_id=entity_id,
                    after_commit=cursor_commit,
                    bound_commit=bound,
                    page_limit=batch_limit,
                    sources=sources,
                )
                rows = format_dataset_rows(raw_events, selected)
                if rows:
                    copy_rows_on(
                        conn,
                        relation,
                        copy_columns,
                        rows,
                        start_ord=row_count + 1,
                    )
                    row_count += len(rows)

            if summary.scanned_count == 0:
                has_more = False
                break

            assert summary.last_commit_seq is not None
            assert summary.last_seq is not None
            progress = IncrementalPosition(
                commit_seq=summary.last_commit_seq,
                seq=summary.last_seq,
            )
            cursor_commit = summary.last_commit_seq
            scanned += summary.scanned_count
            has_more = summary.has_more
            if on_page_size is not None:
                on_page_size(relation_size_on(conn, relation))
            if not summary.has_more:
                break

        if before_page is not None:
            rem_ms = before_page()
            if rem_ms is not None:
                set_write_timeouts(conn, max(1, int(rem_ms)))
        analyze_on(conn, relation)
        size = relation_size_on(conn, relation)

    return IncrementalDatasetResult(
        row_count=row_count,
        size_bytes=size,
        progress=progress,
        has_more=has_more,
    )


def _authorize(entity_id: str, user: UserRecord) -> tuple[Any, Any, Person]:
    head = load_head(entity_id)
    revision = get_access_store().revision(entity_id)
    person = Person(
        user_id=user.id,
        role_id=user.role_id,
        group_ids=user_group_ids(user.id),
    )
    policy = load_policy(head, revision, people=(person,))
    compiled = compile_decisions(policy)
    if (
        compiled.shapes
        and frozen_reference_bindings_cover(
            list(policy.source_attributes), policy.reference_snapshots
        )
        is None
    ):
        raise EntityNotServing(_SERVING_HEAD_PREDATES)
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
    return policy, outcome, person


def _versions(entity_id: str) -> dict[str, VersionMeta]:
    found: dict[str, VersionMeta] = {}
    for table in change_log_tables(entity_id):
        assert table.version_id is not None
        assert table.version_number is not None
        found[table.physical_table] = VersionMeta(
            version_id=table.version_id,
            version_number=table.version_number,
            table=table,
        )
    return found


def _project(
    conn: Any,
    entries: list[ChangeLogEntry],
    index: dict[str, VersionMeta],
    policy: Any,
    outcome: Any,
    person: Person,
) -> list[tuple[ChangeLogEntry, str, int, HistorySide, HistorySide]]:
    works: list[SideWork] = []
    located: list[tuple[ChangeLogEntry, VersionMeta]] = []
    for entry in entries:
        version = index[entry.physical_table]
        located.append((entry, version))
        snapshots = version.table.reference_snapshots
        attributes = version.table.attributes
        works.append(
            SideWork(
                image=entry.before,
                attributes=attributes,
                reference_snapshots=snapshots,
            )
        )
        works.append(
            SideWork(
                image=entry.after,
                attributes=attributes,
                reference_snapshots=snapshots,
            )
        )
    projected = project_sides(conn, works, policy, outcome, person)
    return [
        (
            entry,
            version.version_id,
            version.version_number,
            projected[2 * offset],
            projected[2 * offset + 1],
        )
        for offset, (entry, version) in enumerate(located)
    ]


def _projected_key_name(version: VersionMeta, policy: Any) -> str | None:
    """Current attribute name of the key that version declares.

    None means the version declares no Business Key. A declared key that has
    left the head still returns the stored name, so a consumer does not treat
    the version as unkeyed.
    """
    historical = version.table.business_key
    if not historical:
        return None
    attr = next(
        (item for item in version.table.attributes if item.name == historical),
        None,
    )
    attribute_id = None if attr is None else attr.attribute_id
    if attribute_id:
        for fact in policy.attributes:
            if fact.attribute_id == attribute_id:
                return str(fact.name)
    return historical


def _eligible(before: HistorySide, after: HistorySide) -> bool:
    return before.state == "visible" or after.state == "visible"


def _same_projection(before: HistorySide, after: HistorySide) -> bool:
    return (
        before.state == "visible"
        and after.state == "visible"
        and before.values == after.values
    )


def _key_can_be_clear(index: dict[str, VersionMeta], outcome: Any) -> bool:
    """True when some version's Business Key can be a clear cell.

    Always masked, always withheld, and absent from the caller's shape are
    not clear. A row-varying mask still counts when one grant mode is clear.
    """
    for version in index.values():
        attribute_id = _business_key_id(version)
        if attribute_id is None:
            continue
        for column in outcome.columns:
            if column.attr.attribute_id != attribute_id:
                continue
            if any(mode == CLEAR for _grant_id, mode in column.grant_modes):
                return True
    return False


def _business_key_id(version: VersionMeta) -> str | None:
    name = version.table.business_key
    if not name:
        return None
    for attr in version.table.attributes:
        if attr.name == name and attr.attribute_id:
            return attr.attribute_id
    return None


def _version_row(
    index: dict[str, VersionMeta], lookup: HistoryLookup
) -> tuple[str, str] | None:
    if lookup.row_id is None:
        return None
    for version in index.values():
        if version.version_id == lookup.version_id:
            return (version.table.physical_table, str(lookup.row_id))
    return None


def _lookup_hit(
    version: VersionMeta,
    before: HistorySide,
    after: HistorySide,
    lookup: HistoryLookup,
    policy: Any,
) -> bool:
    if lookup.row_identity is None and lookup.row_id is None:
        return True
    if lookup.row_identity is not None:
        name = _projected_key_name(version, policy)
        return _key_hit(before, name, lookup.row_identity) or _key_hit(
            after, name, lookup.row_identity
        )
    return _row_hit(before, lookup.row_id) or _row_hit(after, lookup.row_id)


def _key_hit(side: HistorySide, name: str | None, query: str) -> bool:
    if name is None:
        return False
    value = clear_cell(side, name)
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, str):
        return value == query
    if isinstance(value, int):
        return str(value) == query
    return False


def _row_hit(side: HistorySide, row_id: int | None) -> bool:
    value = clear_cell(side, "row_id")
    return isinstance(value, int) and not isinstance(value, bool) and value == row_id


def clear_cell(side: HistorySide, name: str) -> Any:
    """A visible cell that is present, not masked, and not withheld.

    ``None`` means the cell is not a clear value. A stored null is also
    ``None``.
    """
    if side.state != "visible" or side.values is None:
        return None
    if name in side.masked:
        return None
    if name not in side.values:
        return None
    withheld = side.values.get("__withheld")
    if isinstance(withheld, list) and name in {str(item) for item in withheld}:
        return None
    return side.values[name]
