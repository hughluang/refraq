"""Prepare one Entity SQL statement for validation and later execution.

The gate runs first, then each referenced Entity is decided in ``table_name``
order. This step never opens an entity connection and never writes an Entity
Access Log record. ``begin_data`` logs the pending outcome, so the decision
here calls the same lower-level steps and lets that error propagate.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace

from backend.admin.user_store import UserRecord
from backend.entity.access.compiler import compile_policy
from backend.entity.access.enforce import (
    DataAccess,
    _subject_outcome,
    shape_names,
)
from backend.entity.access.errors import EntityAccessCombinationLimit
from backend.entity.access.membership import person_of, readable_entity_ids
from backend.entity.access.plan import load_head, load_policy
from backend.entity.access.service import _ensure_generated
from backend.entity.access.store import get_access_store
from backend.entity.data.head import resolve_head
from backend.entity.ddl import ENTITY_ACCESS_SCHEMA, qualified_table
from backend.entity.errors import EntityNotFound, EntitySqlInvalid
from backend.entity.sql_gate import (
    EntitySqlError as GateSqlError,
    EntitySqlNotFound as GateSqlNotFound,
    bind_entity_sql,
)
from backend.entity.store import get_entity_store

_PLACEHOLDER = qualified_table(ENTITY_ACCESS_SCHEMA, "placeholder")
_OVER_LIMIT = "access configuration over limit for this subject"


@dataclass(frozen=True, slots=True)
class PartialColumn:
    """One row-varying column the statement names."""

    table_name: str
    column: str


@dataclass(frozen=True, slots=True)
class PreparedSql:
    """Bound statement and the per-Entity facts execution needs.

    ``submitted_sql`` is the caller's text. A tool may echo it and must not
    echo ``bound_sql``. ``entities`` is the referenced ``table_name`` values,
    sorted. ``partial_columns`` is sorted by ``table_name`` then ``column``.
    ``decisions[i]`` is the read :class:`DataAccess` for ``entities[i]``:
    ``policy`` and ``compiled`` for signing, ``outcome.grant_ids``,
    ``outcome.shape.view_name``, ``revision``, and ``target.entity.id`` for
    the access log, and ``target.read_relation`` as the bound relation.
    ``views`` maps each bare Profile View name to that Entity's ``table_name``
    so a database error can replace the view identifier.
    """

    submitted_sql: str
    bound_sql: str
    entities: tuple[str, ...]
    partial_columns: tuple[PartialColumn, ...]
    decisions: tuple[DataAccess, ...]
    views: dict[str, str]


def prepare_entity_sql(sql: str, user: UserRecord) -> PreparedSql:
    """Gate, bind, and resolve read access for every referenced Entity.

    The first failure wins: a gate rejection, then an unknown or invisible
    name, then each referenced Entity in ``table_name`` order.
    """

    relations = _visible_relations(user)
    probed = _gate(sql, relations)
    decisions: list[DataAccess] = []
    varying: dict[str, frozenset[str]] = {}
    views: dict[str, str] = {}
    bound_relations = dict(relations)
    for table_name in sorted(probed.entities):
        access = _decide_read(table_name, user)
        decisions.append(access)
        varying[table_name] = frozenset(
            column.attr.name
            for column in access.outcome.columns
            if column.row_varying
        )
        # _decide_read raises unless the outcome has a shape and read relation.
        views[access.outcome.shape.view_name] = table_name
        bound_relations[table_name] = access.target.read_relation
    bound = _gate(sql, bound_relations, varying)
    partial = tuple(
        sorted(
            (
                PartialColumn(item.table_name, item.column)
                for item in bound.partial_columns
            ),
            key=lambda item: (item.table_name, item.column),
        )
    )
    return PreparedSql(
        submitted_sql=sql,
        bound_sql=bound.bound_sql,
        entities=tuple(sorted(bound.entities)),
        partial_columns=partial,
        decisions=tuple(decisions),
        views=views,
    )


def _visible_relations(user: UserRecord) -> dict[str, str]:
    """Visible ``table_name`` values, including deprecated and not-serving ones.

    The placeholder relation is only for the probe bind. The bound statement
    uses each Entity's Profile View after the access decision.
    """

    entities = get_entity_store().list_all_entities()
    visible = readable_entity_ids(
        [entity.id for entity in entities], person_of(user)
    )
    return {
        entity.table_name: _PLACEHOLDER
        for entity in entities
        if entity.id in visible
    }


def _gate(
    sql: str,
    relations: dict[str, str],
    varying: dict[str, frozenset[str]] | None = None,
):
    try:
        return bind_entity_sql(
            sql, relations=relations, row_varying_columns=varying
        )
    except GateSqlNotFound as exc:
        raise _not_found(exc.name) from exc
    except GateSqlError as exc:
        raise EntitySqlInvalid(exc.message) from exc


def _decide_read(table_name: str, user: UserRecord) -> DataAccess:
    """Read decision matching ``begin_data`` without its pending log write."""

    started = time.perf_counter()
    entity = get_entity_store().get_entity_by_table_name(table_name)
    if entity is None:
        raise _not_found(table_name)
    head = load_head(entity.id)
    revision = get_access_store().revision(entity.id)
    person = person_of(user)
    policy = load_policy(head, revision, people=(person,))
    compiled = compile_policy(policy)
    base = _subject_outcome(head, revision, person, policy, compiled, "read", None)
    if base.over_limit:
        raise EntityAccessCombinationLimit(_OVER_LIMIT)
    if not base.grant_ids:
        raise _not_found(table_name)
    _ensure_generated(head, base, revision, user_id=user.id)
    target = resolve_head(table_name, for_write=False)
    outcome = _subject_outcome(
        head, revision, person, policy, compiled, "read", None
    )
    if outcome.over_limit:
        raise EntityAccessCombinationLimit(_OVER_LIMIT)
    if not outcome.grant_ids or outcome.shape is None:
        raise _not_found(table_name)
    _ensure_generated(head, outcome, revision, user_id=user.id)
    names = shape_names(outcome)
    shaped = tuple(attr for attr in target.attributes if attr.name in names)
    view = qualified_table(ENTITY_ACCESS_SCHEMA, outcome.shape.view_name)
    narrowed = replace(target, attributes=shaped, read_relation=view)
    return DataAccess(
        user=user,
        head=head,
        target=narrowed,
        full=target,
        outcome=outcome,
        policy=policy,
        compiled=compiled,
        person=person,
        narrow=None,
        revision=revision,
        action="read",
        started=started,
    )


def _not_found(table_name: str) -> EntityNotFound:
    return EntityNotFound(
        f"Business Entity with table_name '{table_name}' was not found"
    )
