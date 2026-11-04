"""A whole Channel Run: Changes Dataset, Batch Read, and Write Entity.

Seam: run outcome, rows written, and the stored cursor after settle_success.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from backend.channel.checkpoints import CheckpointPosition, RunCheckpoints, get_checkpoint_store
from backend.channel.engine import execute
from backend.channel.nodes import list_node_types
from backend.channel.recovery import settle_success
from backend.channel.run_store import ChannelRunRecord, get_run_store
from backend.core.time import utc_now
from backend.entity.changes import ChangePosition, capture_bound, read_changes
from backend.entity.ddl import ENTITY_DATA_SCHEMA, qualified_table
from backend.jobs.store import get_job_store
from backend.tests.channel_hooks_fake import FakeHooks
from backend.tests.test_channel_engine import _RESOLVER, _edge, _node

pytestmark = pytest.mark.integration

_MAINTENANCE = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)
_CHANNEL_ID = "chn_changes_dataset"
_NODE_ID = "changes"
_LIMIT = 10
_BACKLOG = 30
_LATER = 10
_BATCH = 5


def _postgres_available() -> bool:
    try:
        engine = create_engine(_MAINTENANCE)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


class _Map(dict):
    """Dict whose keys are also attributes, for ``self.node.output.field``."""

    def __getattr__(self, name: str) -> Any:
        try:
            value = self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc
        if isinstance(value, dict) and not isinstance(value, _Map):
            return _Map(value)
        return value


class _Output:
    def __init__(self, output: Any) -> None:
        self.output = _Map(output) if isinstance(output, dict) else output


class _RunHooks(FakeHooks):
    """FakeHooks with the execute_path template evaluator and a run checkpoint session."""

    def evaluate(self, expression: str) -> Any:
        hooks = self

        class _Self:
            def __getattr__(self, ref: str) -> Any:
                if ref not in hooks.outputs:
                    raise AttributeError(ref)
                return _Output(hooks.outputs[ref])

        return eval(  # noqa: S307 - templates are fixed strings in this harness
            expression,
            {"__builtins__": {"dict": dict}},
            {"self": _Self()},
        )


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch):
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")
    from backend.admin.roles import seed_roles
    from backend.admin.role_store import get_role_store
    from backend.admin.security import hash_password
    from backend.admin.system_parameters import reset_parameter_registry
    from backend.admin.user_store import get_user_store
    from backend.channel.dataset_registry import reset_dataset_store
    from backend.core.config import get_settings, reset_settings_cache
    from backend.entity.access import enforce
    from backend.entity.data import sql as data_sql
    from backend.entity.entity_db import (
        get_entity_engine,
        get_entity_reader_engine,
        reset_entity_engine,
    )
    from backend.entity.store import reset_entity_store
    from backend.entity.table_port import PostgresEntityTablePort, bind_entity_table_port
    from backend.tests.entity_pg import bootstrapped_entity_database
    from backend.worker.parameters import assemble_system_parameters

    os.environ.setdefault("REFRAQ_SECRETS_MASTER_KEY", "test-secrets-master-key")
    os.environ.setdefault("CELERY_BROKER_URL", "memory://")
    os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "1")
    with bootstrapped_entity_database(_MAINTENANCE, "refraq_cdrun") as urls:
        monkeypatch.setenv("ENTITY_DATABASE_URL", urls.owner_url)
        monkeypatch.setenv("ENTITY_READER_DATABASE_URL", urls.reader_url)
        monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        reset_settings_cache()
        reset_entity_engine()
        reset_entity_store()
        monkeypatch.setattr(data_sql, "require_entity_capacity", get_entity_engine)
        monkeypatch.setattr(
            data_sql, "require_entity_reader_capacity", get_entity_reader_engine
        )
        signing = get_settings().model_copy(update={"store_backend": "persistent"})
        monkeypatch.setattr(enforce, "get_settings", lambda: signing)
        bind_entity_table_port(PostgresEntityTablePort())
        roles = get_role_store()
        seed_roles(roles)
        admin_role = roles.get_by_key("super_admin")
        assert admin_role is not None
        get_user_store().create_user(
            account="admin",
            display_name="Admin",
            password_hash=hash_password("secret"),
            role_id=admin_role.id,
            status="active",
        )
        admin = get_user_store().get_by_account("admin")
        assert admin is not None
        assemble_system_parameters()
        reset_dataset_store()
        source_id, source_table = _publish("Source", arm_change_log=True)
        target_id, _target_table = _publish("Target", arm_change_log=False)
        targets = SimpleNamespace(
            channel_id=_CHANNEL_ID,
            source_id=source_id,
            source_table=source_table,
            target_id=target_id,
            user=admin,
        )
        try:
            yield targets
        finally:
            reset_dataset_store()
            reset_parameter_registry()
            reset_entity_engine()
            reset_entity_store()
            reset_settings_cache()


def _sku_attrs() -> list:
    from backend.entity.records import AttributeRecord

    return [
        AttributeRecord(
            name="sku",
            type="string",
            required=True,
            unique=True,
            business_key=True,
            max_length=32,
        ),
        AttributeRecord(name="qty", type="integer"),
    ]


def _publish(label: str, *, arm_change_log: bool) -> tuple[str, str]:
    from backend.entity.change_log import (
        ChangeLogEffective,
        ensure_shared_relations,
        install_triggers,
        write_effective,
    )
    from backend.entity.entity_db import get_entity_engine
    from backend.entity.ids import new_entity_id, new_version_id
    from backend.entity.lifecycle import PUBLISHED
    from backend.entity.records import (
        BusinessEntityRecord,
        EntityVersionRecord,
        attribute_to_dict,
    )
    from backend.entity.store import get_entity_store
    from backend.entity.table_name import compose_physical_table_name
    from backend.entity.table_port import PostgresEntityTablePort
    from backend.tests.entity_access_oracle import prepare_legacy_entity

    attrs = _sku_attrs()
    stem = f"cd_{uuid.uuid4().hex[:8]}"
    version_id = new_version_id()
    physical, _shortened = compose_physical_table_name(stem, 1, version_id)
    now = datetime.now(timezone.utc)
    entity = BusinessEntityRecord(
        id=new_entity_id(),
        table_name=stem,
        name=label,
        description="Changes Dataset channel run",
        deprecated_at=None,
        created_at=now,
        updated_at=now,
    )
    version = EntityVersionRecord(
        id=version_id,
        entity_id=entity.id,
        version=1,
        attributes=list(attrs),
        materialized_attributes=[attribute_to_dict(item) for item in attrs],
        publish_status=PUBLISHED,
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
    )
    get_entity_store().create_entity(entity, version)
    port = PostgresEntityTablePort()
    port.create_physical_table(ENTITY_DATA_SCHEMA, physical, attrs)
    port.swap_stem_view(ENTITY_DATA_SCHEMA, stem, physical=physical, expected_target=None)
    prepare_legacy_entity(entity.id)
    if arm_change_log:
        with get_entity_engine().begin() as conn:
            ensure_shared_relations(conn)
            write_effective(
                conn,
                ChangeLogEffective(
                    entity_id=entity.id,
                    recording=True,
                    retention_days=None,
                    applied_version_id=version_id,
                ),
            )
            install_triggers(conn, entity.id, [physical])
    return entity.id, physical


def _relation(table: str) -> str:
    return qualified_table(ENTITY_DATA_SCHEMA, table)


def _insert(conn: Connection, table: str, sku: str, qty: int) -> None:
    conn.execute(
        text(f"INSERT INTO {_relation(table)} (sku, qty) VALUES (:sku, :qty)"),
        {"sku": sku, "qty": qty},
    )


def _update_qty(conn: Connection, table: str, sku: str, qty: int) -> None:
    conn.execute(
        text(f"UPDATE {_relation(table)} SET qty = :qty WHERE sku = :sku"),
        {"sku": sku, "qty": qty},
    )


def _sku(index: int) -> str:
    return f"S{index:03d}"


def _graph(source_id: str, target_id: str, *, limit: int, batch_size: int) -> dict:
    changes = _node(_NODE_ID, 0, type_id="volume.changes_dataset")
    changes["config"] = {
        "entity_id": source_id,
        "limit": limit,
        "statement_timeout_sec": 300,
    }
    batch = _node("batch", 1, type_id="volume.batch_read")
    batch["config"] = {
        "dataset": "{{ self.changes.output.dataset }}",
        "batch_size": batch_size,
    }
    fields = _node("fields", 2, type_id="transform.set_fields", parent="batch")
    fields["config"] = {
        "fields": [
            {
                "name": "rows",
                "value": (
                    "{{ [{'sku': row['after']['sku'], 'qty': row['after']['qty']} "
                    "for row in self.batch.output.rows] }}"
                ),
            }
        ],
    }
    write = _node("write", 3, type_id="write.entity", parent="batch")
    write["config"] = {
        "entity_id": target_id,
        "mode": "upsert",
        "match_key": "sku",
        "source": "{{ self.fields.output.rows }}",
        "mapping": [
            {"attribute": "sku", "key": "sku"},
            {"attribute": "qty", "key": "qty"},
        ],
        "on_incompatible_head": "fail",
        "statement_timeout_sec": 300,
    }
    return {
        "nodes": [changes, batch, fields, write],
        "edges": [
            _edge("changes", "batch"),
            _edge("batch", "fields", "each"),
            _edge("fields", "write"),
        ],
        "settings": {},
    }


def _open_run(channel_id: str, run_id: str) -> ChannelRunRecord:
    record = ChannelRunRecord(
        job_id=run_id,
        channel_id=channel_id,
        target="draft",
        version=None,
        draft_revision=1,
        graph=None,
        trigger_node_id=_NODE_ID,
        ignore_checkpoints=False,
        outcome=None,
        failed_node_id=None,
        skipped_node_ids=[],
        created_at=utc_now(),
        stop_at_node_id=None,
    )
    get_run_store().insert_run(record)
    return record


def _channel_job_ids() -> list[str]:
    rows, _total = get_job_store().list(kind="channel_run")
    return [row.id for row in rows]


def _cursor(source_id: str) -> CheckpointPosition | None:
    return get_checkpoint_store().read(_CHANNEL_ID, _NODE_ID, source_id)


def _target_rows(targets: Any) -> list[tuple[str, int | None]]:
    from backend.entity.rows import read_rows

    rows, _total = read_rows(targets.target_id, filters=[], user=targets.user, limit=100)
    return sorted((str(row["sku"]), row.get("qty")) for row in rows)


def _position(entry: Any) -> CheckpointPosition:
    return CheckpointPosition(xact=entry.xact, seq=entry.sequence)


def _execute_run(targets: Any, *, limit: int, batch_size: int) -> Any:
    run_id = f"cdrun-{uuid.uuid4().hex[:8]}"
    record = _open_run(targets.channel_id, run_id)
    hooks = _RunHooks(run_id=run_id, channel_id=targets.channel_id, user=targets.user)
    hooks.checkpoints = RunCheckpoints(targets.channel_id, record)
    graph = _graph(targets.source_id, targets.target_id, limit=limit, batch_size=batch_size)
    before_jobs = _channel_job_ids()
    outcome = execute(graph, _NODE_ID, list(list_node_types()), _RESOLVER, hooks)
    record.outcome = outcome.outcome
    record.failed_node_id = outcome.failed_node_id
    record.stopped_node_id = outcome.stopped_node_id
    if outcome.status == "succeeded":
        settle_success(record)
    assert _channel_job_ids() == before_jobs
    return SimpleNamespace(outcome=outcome, hooks=hooks, record=record)


def test_a_3n_backlog_drains_in_three_completed_runs_then_ten_later_updates(
    harness,
) -> None:
    from backend.entity.entity_db import get_entity_engine

    with get_entity_engine().begin() as conn:
        for index in range(1, _BACKLOG + 1):
            _insert(conn, harness.source_table, _sku(index), index)
    backlog = read_changes(
        harness.source_id,
        after=None,
        bound=capture_bound(harness.source_id),
        limit=_BACKLOG + 1,
    )
    assert len(backlog.entries) == _BACKLOG
    assert backlog.has_more is False
    assert _cursor(harness.source_id) is None

    for step in range(1, 4):
        result = _execute_run(harness, limit=_LIMIT, batch_size=_BATCH)
        assert result.outcome.status == "succeeded", result.outcome.error_message
        assert result.outcome.outcome == "completed"
        assert result.outcome.stopped_node_id is None
        assert result.hooks.outputs["changes"]["count"] == _LIMIT
        assert result.hooks.outputs["batch"]["total"] == _LIMIT
        assert _target_rows(harness) == [
            (_sku(index), index) for index in range(1, step * _LIMIT + 1)
        ]
        assert _cursor(harness.source_id) == _position(backlog.entries[step * _LIMIT - 1])

    with get_entity_engine().begin() as conn:
        for index in range(1, _LATER + 1):
            _update_qty(conn, harness.source_table, _sku(index), 100 + index)
    later = read_changes(
        harness.source_id,
        after=ChangePosition(
            xact=backlog.entries[-1].xact, seq=backlog.entries[-1].sequence
        ),
        bound=capture_bound(harness.source_id),
        limit=_LATER + 1,
    )
    assert len(later.entries) == _LATER
    assert later.has_more is False

    result = _execute_run(harness, limit=_LIMIT, batch_size=_BATCH)
    assert result.outcome.status == "succeeded", result.outcome.error_message
    assert result.outcome.outcome == "completed"
    assert result.hooks.outputs["changes"]["count"] == _LATER
    assert result.hooks.outputs["batch"]["total"] == _LATER
    assert _target_rows(harness) == [
        (_sku(index), 100 + index if index <= _LATER else index)
        for index in range(1, _BACKLOG + 1)
    ]
    assert _cursor(harness.source_id) == _position(later.entries[-1])


def test_a_later_batch_write_failure_leaves_the_cursor_and_the_next_run_converges(
    harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.entity.entity_db import get_entity_engine
    from backend.entity.errors import EntityRowWriteFailed
    from backend.entity.rows import write_rows

    extra = _LIMIT
    with get_entity_engine().begin() as conn:
        for index in range(1, _LIMIT + extra + 1):
            _insert(conn, harness.source_table, _sku(index), index)
    page = read_changes(
        harness.source_id,
        after=None,
        bound=capture_bound(harness.source_id),
        limit=_LIMIT + extra + 1,
    )
    assert len(page.entries) == _LIMIT + extra
    cut = _position(page.entries[_LIMIT - 1])
    assert _cursor(harness.source_id) is None

    calls = {"n": 0}

    def fail_later(*args: Any, **kwargs: Any):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise EntityRowWriteFailed(
                "later batch rejected", row_index=0, reason="invalid"
            )
        return write_rows(*args, **kwargs)

    monkeypatch.setattr("backend.channel.nodes.write.entity.write_rows", fail_later)
    failed = _execute_run(harness, limit=_LIMIT, batch_size=_BATCH)
    assert failed.outcome.status == "failed", failed.outcome.error_message
    assert failed.outcome.outcome is None
    assert failed.outcome.failed_node_id == "write"
    assert failed.record.outcome is None
    assert _cursor(harness.source_id) is None
    assert len(_target_rows(harness)) == _BATCH

    monkeypatch.setattr("backend.channel.nodes.write.entity.write_rows", write_rows)
    replay = _execute_run(harness, limit=_LIMIT, batch_size=_BATCH)
    assert replay.outcome.status == "succeeded", replay.outcome.error_message
    assert replay.outcome.outcome == "completed"
    assert replay.hooks.outputs["changes"]["count"] == _LIMIT
    assert replay.hooks.outputs["batch"]["total"] == _LIMIT
    assert _target_rows(harness) == [(_sku(index), index) for index in range(1, _LIMIT + 1)]
    assert _cursor(harness.source_id) == cut
