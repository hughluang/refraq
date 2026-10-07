"""Drop and create every profile view for one Entity in one entity-database transaction.

Shape changes use DROP + CREATE. CREATE OR REPLACE cannot change a view's columns.
"""

from __future__ import annotations

from typing import Any

from backend.entity.access.compiler import (
    Binding,
    CompiledPolicy,
    compile_policy,
    script_statements,
)
from backend.entity.access.plan import Head, load_head, load_policy
from backend.entity.access.records import BindingRecord
from backend.entity.access.store import get_access_store
from backend.entity.ddl import ENTITY_ACCESS_SCHEMA, qualified_table
from backend.entity.table_port import get_entity_table_port

__all__ = [
    "READY",
    "persist_ready",
    "profile_view_statements",
    "rebuild_entity_views",
    "restore_profile_views",
]

READY = "ready"


def profile_view_statements(
    compiled: CompiledPolicy, previous_names: list[str]
) -> list[str]:
    """DROP every previous and new view, then CREATE, set owner, and grant."""
    creates: list[str] = []
    names: list[str] = []
    for binding in compiled.bindings:
        names.append(binding.view_name)
        creates.extend(script_statements(binding.view_name, binding.sql))
    drop_names = list(dict.fromkeys([*previous_names, *names]))
    drops = [
        f"DROP VIEW IF EXISTS {qualified_table(ENTITY_ACCESS_SCHEMA, name)}"
        for name in drop_names
    ]
    return [*drops, *creates]


def rebuild_entity_views(entity_id: str) -> dict[str, Any]:
    """Recompile the latest revision and replace that Entity's profile views."""
    store = get_access_store()
    head = load_head(entity_id)
    revision = store.revision(entity_id)
    previous = store.bindings(entity_id)
    if head.physical is None or head.version_id is None:
        store.replace_bindings(entity_id, [])
        store.set_views_revision(entity_id, revision)
        return _result(revision, created=0, dropped=len(previous), compiled=None)
    compiled = compile_policy(load_policy(head, revision))
    statements = profile_view_statements(
        compiled, [item.view_name for item in previous]
    )
    get_entity_table_port().execute_ddl(statements)
    created = persist_ready(head, compiled, revision)
    return _result(
        revision,
        created=created,
        dropped=len({item.view_name for item in previous}),
        compiled=compiled,
    )


def persist_ready(head: Head, compiled: CompiledPolicy, revision: int) -> int:
    """Store bindings after the entity-database transaction has committed."""
    if head.version_id is None:
        get_access_store().replace_bindings(head.entity_id, [])
        get_access_store().set_views_revision(head.entity_id, revision)
        return 0
    records = [_ready_record(head, item, revision) for item in compiled.bindings]
    store = get_access_store()
    store.replace_bindings(head.entity_id, records)
    store.set_views_revision(head.entity_id, revision)
    return len(records)


def restore_profile_views(
    scripts: list[tuple[str, str]], drop_names: list[str]
) -> None:
    """Put the previous ``(view_name, create script)`` pairs back after a publish failure."""
    drops = [
        f"DROP VIEW IF EXISTS {qualified_table(ENTITY_ACCESS_SCHEMA, name)}"
        for name in dict.fromkeys(drop_names)
    ]
    creates: list[str] = []
    for view_name, script in scripts:
        creates.extend(script_statements(view_name, script))
    statements = [*drops, *creates]
    if statements:
        get_entity_table_port().execute_ddl(statements)


def _ready_record(head: Head, binding: Binding, revision: int) -> BindingRecord:
    return BindingRecord(
        entity_id=head.entity_id,
        head_version_id=head.version_id or "",
        policy_revision=revision,
        combo_key=binding.combo_key,
        shape_key=binding.shape_key,
        action=binding.action,
        view_name=binding.view_name,
        columns=list(binding.columns),
        ddl_sha256=binding.ddl_sha256,
        status=READY,
        sql=binding.sql,
    )


def _result(
    revision: int,
    *,
    created: int,
    dropped: int,
    compiled: CompiledPolicy | None,
) -> dict[str, Any]:
    return {
        "schema": "entity_access_views.v1",
        "policy_revision": revision,
        "views_created": created,
        "views_dropped": dropped,
        "combinations": 0 if compiled is None else compiled.combinations,
        "subjects_over_limit": 0 if compiled is None else compiled.subjects_over_limit,
    }
