"""250,000-row Dataset Query paths. Peak RSS is this process, not the result objects.

The 1,000,000-row comparison lives in ``dataset_volume_manual`` and is not a test.
"""

from __future__ import annotations

import os
import resource
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import pytest
from sqlalchemy import create_engine, text

_MAINTENANCE = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)
ROWS = 250_000
_NOTE = Path(__file__).resolve().parents[2] / ".process" / "dataset-volume-acceptance.md"
_BATCH = 1000
_TIMEOUT = 3600


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


class _Node:
    def __init__(self, output: Any) -> None:
        self.output = _Map(output) if isinstance(output, dict) else output


class _ClockHooks:
    """Engine hooks that time each execution and resolve ``self.<ref>.output``."""

    def __init__(self, *, run_id: str, user: Any) -> None:
        from backend.tests.channel_hooks_fake import FakeHooks

        self._hooks = FakeHooks(run_id=run_id, user=user)
        self.durations: dict[str, float] = {}
        self.inserted = 0
        self._open: dict[int, tuple[str, float]] = {}

    def __getattr__(self, name: str) -> Any:
        return getattr(self._hooks, name)

    def evaluate(self, expression: str) -> Any:
        hooks = self._hooks

        class _Self:
            def __getattr__(self, ref: str) -> Any:
                if ref not in hooks.outputs:
                    raise AttributeError(ref)
                return _Node(hooks.outputs[ref])

        return eval(  # noqa: S307 - templates are fixed strings in this harness
            expression,
            {"__builtins__": {"dict": dict}},
            {"self": _Self()},
        )

    def on_start(self, node: dict, *, container_seq: int | None = None, round: int | None = None) -> int:
        seq = self._hooks.on_start(node, container_seq=container_seq, round=round)
        self._open[seq] = (str(node["id"]), time.perf_counter())
        return seq

    def on_finish(self, seq: int, node: dict, result: Any) -> None:
        self._hooks.on_finish(seq, node, result)
        started = self._open.pop(seq, None)
        if started is not None:
            node_id, opened = started
            self.durations[node_id] = self.durations.get(node_id, 0.0) + (time.perf_counter() - opened)
        if (
            str(node["id"]) == "write"
            and getattr(result, "status", None) == "succeeded"
            and isinstance(result.output, dict)
        ):
            self.inserted += int(result.output.get("inserted") or 0)

    def drop_outputs(self, refs: list[str]) -> None:
        del refs


def _vm_rss() -> int:
    try:
        with open("/proc/self/status", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


def _peak_during(work):
    """Sample this process's current RSS while ``work`` runs."""
    peak = _vm_rss()
    stop = threading.Event()

    def sample() -> None:
        nonlocal peak
        while not stop.wait(0.05):
            current = _vm_rss()
            if current > peak:
                peak = current

    thread = threading.Thread(target=sample, name="volume-rss", daemon=True)
    thread.start()
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    try:
        value = work()
    finally:
        stop.set()
        thread.join(timeout=1)
        peak = max(peak, _vm_rss())
    after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value, peak, before, after


def _series_sql(rows: int) -> str:
    count = int(rows)
    return (
        "SELECT n::text AS sku, n::integer AS qty "
        f"FROM generate_series(1, {count}) AS n"
    )


def _write_config(entity_id: str, source: str) -> dict:
    return {
        "entity_id": entity_id,
        "mode": "create",
        "match_key": "sku",
        "source": source,
        "mapping": [
            {"attribute": "sku", "key": "sku"},
            {"attribute": "qty", "key": "qty"},
        ],
        "on_incompatible_head": "fail",
        "statement_timeout_sec": _TIMEOUT,
    }


def _graph(path: str, entity_id: str, rows: int) -> dict:
    from backend.tests.test_channel_engine import _edge, _node

    query = _node("query", 0, type_id="volume.dataset_query")
    query["config"] = {
        "source": {"kind": "entity"},
        "sql": _series_sql(rows),
        "statement_timeout_sec": _TIMEOUT,
    }
    write = _node("write", 3, type_id="write.entity")
    if path == "direct":
        write["config"] = _write_config(entity_id, "{{ self.query.output.dataset }}")
        return {
            "nodes": [query, write],
            "edges": [_edge("query", "write")],
            "settings": {},
        }
    batch = _node("batch", 1, type_id="volume.batch_read")
    batch["config"] = {
        "dataset": "{{ self.query.output.dataset }}",
        "batch_size": _BATCH,
    }
    fields = _node("fields", 2, type_id="transform.set_fields", parent="batch")
    fields["config"] = {
        "fields": [
            {
                "name": "rows",
                "value": "{{ [dict(row, note='kept') for row in self.batch.output.rows] }}",
            }
        ],
    }
    write["parent"] = "batch"
    write["config"] = _write_config(entity_id, "{{ self.fields.output.rows }}")
    return {
        "nodes": [query, batch, fields, write],
        "edges": [
            _edge("query", "batch"),
            _edge("batch", "fields", "each"),
            _edge("fields", "write"),
        ],
        "settings": {},
    }


def _table_stats(physical: str) -> dict[str, int | None]:
    from backend.entity.ddl import qualified_table
    from backend.entity.entity_db import get_entity_engine

    relation = qualified_table("entity_data", physical)
    statement = text(
        "SELECT count(*)::bigint, "
        "count(*) FILTER (WHERE note = 'kept')::bigint, "
        "count(*) FILTER (WHERE note IS NULL)::bigint, "
        "min(qty), max(qty) "
        f"FROM {relation}"
    )
    with get_entity_engine().connect() as conn:
        row = conn.execute(statement).one()
    return {
        "row_count": int(row[0]),
        "note_kept": int(row[1]),
        "note_null": int(row[2]),
        "qty_min": None if row[3] is None else int(row[3]),
        "qty_max": None if row[4] is None else int(row[4]),
    }


def execute_path(targets: Any, path: str, rows: int) -> dict[str, Any]:
    """Run one path. ``path`` is ``slow`` or ``direct``."""
    from backend.channel.engine import execute
    from backend.channel.nodes import list_node_types
    from backend.tests.test_channel_engine import _RESOLVER

    entity_id = targets.slow_entity_id if path == "slow" else targets.direct_entity_id
    physical = targets.slow_physical if path == "slow" else targets.direct_physical
    hooks = _ClockHooks(run_id=f"vol-{path}-{rows}-{uuid.uuid4().hex[:8]}", user=targets.user)
    graph = _graph(path, entity_id, rows)

    def run():
        return execute(graph, "query", list(list_node_types()), _RESOLVER, hooks)

    outcome, peak, before_kb, after_kb = _peak_during(run)
    if outcome.status != "succeeded":
        raise AssertionError(
            f"{path} {outcome.status} node={outcome.failed_node_id} "
            f"{outcome.error_code} {outcome.error_message}"
        )
    query = hooks.outputs.get("query") or {}
    if query.get("count") != rows:
        raise AssertionError(f"{path} dataset count {query.get('count')} != {rows}")
    if path == "slow":
        done = hooks.outputs.get("batch") or {}
        expected_batches = (rows + _BATCH - 1) // _BATCH
        if done.get("total") != rows or done.get("count") != expected_batches:
            raise AssertionError(f"{path} batch done {done}")
    stats = _table_stats(physical)
    durations = {key: round(value, 3) for key, value in hooks.durations.items()}
    item = {
        "path": path,
        "rows": rows,
        "inserted": hooks.inserted,
        "peak_rss_bytes": peak,
        "ru_maxrss_before_kb": before_kb,
        "ru_maxrss_after_kb": after_kb,
        "durations_sec": durations,
        **stats,
    }
    print(
        f"volume path={path} rows={rows} peak_rss_bytes={peak} "
        f"ru_maxrss_kb={before_kb}->{after_kb} durations_sec={durations} "
        f"inserted={hooks.inserted} row_count={stats['row_count']}",
        file=sys.stderr,
        flush=True,
    )
    return item


def measure_paths(targets: Any, rows: int) -> dict[str, dict[str, Any]]:
    return {
        "slow": execute_path(targets, "slow", rows),
        "direct": execute_path(targets, "direct", rows),
    }


def _setenv(monkeypatch: pytest.MonkeyPatch | None, key: str, value: str) -> None:
    if monkeypatch is None:
        os.environ[key] = value
    else:
        monkeypatch.setenv(key, value)


def _publish(label: str) -> tuple[str, str]:
    from backend.entity.ids import new_entity_id, new_version_id
    from backend.entity.lifecycle import PUBLISHED
    from backend.entity.records import (
        AttributeRecord,
        BusinessEntityRecord,
        EntityVersionRecord,
        attribute_to_dict,
    )
    from backend.entity.store import get_entity_store
    from backend.entity.table_name import compose_physical_table_name as compose_physical
    from backend.entity.table_port import PostgresEntityTablePort
    from backend.tests.entity_access_oracle import prepare_legacy_entity

    stem = f"vol_{uuid.uuid4().hex[:8]}"
    version_id = new_version_id()
    physical, _shortened = compose_physical(stem, 1, version_id)
    attrs = [
        AttributeRecord(
            name="sku",
            type="string",
            required=True,
            unique=True,
            business_key=True,
            max_length=32,
        ),
        AttributeRecord(name="qty", type="integer"),
        AttributeRecord(name="note", type="text"),
    ]
    now = datetime.now(timezone.utc)
    entity = BusinessEntityRecord(
        id=new_entity_id(),
        table_name=stem,
        name=label,
        description="Volume acceptance target",
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
    port.create_physical_table("entity_data", physical, attrs)
    port.swap_stem_view("entity_data", stem, physical=physical, expected_target=None)
    prepare_legacy_entity(entity.id)
    return entity.id, physical


@contextmanager
def volume_database(monkeypatch: pytest.MonkeyPatch | None = None) -> Iterator[Any]:
    """Throwaway entity database with two empty published heads."""
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
    with bootstrapped_entity_database(_MAINTENANCE, "refraq_vol") as urls:
        _setenv(monkeypatch, "ENTITY_DATABASE_URL", urls.owner_url)
        _setenv(monkeypatch, "ENTITY_READER_DATABASE_URL", urls.reader_url)
        _setenv(monkeypatch, "REFRAQ_STORE_BACKEND", "memory")
        if monkeypatch is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            monkeypatch.delenv("DATABASE_URL", raising=False)
        reset_settings_cache()
        reset_entity_engine()
        reset_entity_store()
        if monkeypatch is None:
            data_sql.require_entity_capacity = get_entity_engine  # type: ignore[method-assign]
            data_sql.require_entity_reader_capacity = get_entity_reader_engine  # type: ignore[method-assign]
            signing = get_settings().model_copy(update={"store_backend": "persistent"})
            enforce.get_settings = lambda: signing  # type: ignore[method-assign]
        else:
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
        slow_id, slow_physical = _publish("Volume slow")
        direct_id, direct_physical = _publish("Volume direct")
        targets = SimpleNamespace(
            slow_entity_id=slow_id,
            slow_physical=slow_physical,
            direct_entity_id=direct_id,
            direct_physical=direct_physical,
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


@pytest.fixture
def volume_targets(monkeypatch: pytest.MonkeyPatch):
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")
    with volume_database(monkeypatch) as targets:
        yield targets


def _tail_after_integration(text: str) -> str:
    """Sections after Integration. Rewriting that measurement must keep them."""
    marker = "\n## Integration\n"
    index = text.find(marker)
    search_from = index + len(marker) if index >= 0 else 0
    next_at = text.find("\n## ", search_from)
    if next_at < 0:
        return ""
    return text[next_at + 1 :]


def _write_integration_note(measured: dict[str, dict[str, Any]]) -> None:
    lines = [
        "# Dataset volume acceptance",
        "",
        "## Integration",
        "",
        "Command: `/home/ut/refraq/.venv/bin/python -m pytest backend/tests/test_dataset_volume_acceptance_pg.py -q --tb=line -m integration`",
        "",
        "Peak RSS is the pytest process. `peak_rss_bytes` is the highest VmRSS sampled during the engine run. `ru_maxrss_*_kb` is `resource.getrusage(RUSAGE_SELF).ru_maxrss` (Linux kilobytes, high-water mark since process start). Durations are seconds and are not gated. Batch Read's duration includes its body.",
        "",
        "| path | rows | row_count | inserted | qty | note kept | note null | peak RSS bytes | ru_maxrss before KiB | ru_maxrss after KiB | durations (s) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for path in ("slow", "direct"):
        item = measured[path]
        lines.append(
            "| {path} | {rows} | {row_count} | {inserted} | {qty_min}..{qty_max} | "
            "{note_kept} | {note_null} | {peak_rss_bytes} | {before} | {after} | {durations} |".format(
                path=path,
                rows=item["rows"],
                row_count=item["row_count"],
                inserted=item["inserted"],
                qty_min=item["qty_min"],
                qty_max=item["qty_max"],
                note_kept=item["note_kept"],
                note_null=item["note_null"],
                peak_rss_bytes=item["peak_rss_bytes"],
                before=item["ru_maxrss_before_kb"],
                after=item["ru_maxrss_after_kb"],
                durations=item["durations_sec"],
            )
        )
    lines.append("")
    previous = _NOTE.read_text(encoding="utf-8") if _NOTE.exists() else ""
    tail = _tail_after_integration(previous).strip("\n")
    body = "\n".join(lines).rstrip("\n")
    if tail:
        body = body + "\n\n" + tail
    body += "\n"
    _NOTE.parent.mkdir(parents=True, exist_ok=True)
    _NOTE.write_text(body, encoding="utf-8")


@pytest.mark.integration
def test_dataset_query_paths_write_250_000_rows_and_record_rss(volume_targets) -> None:
    """Dataset Query to Batch Read, Set Fields, and Write, and Dataset Query to Write."""
    measured = measure_paths(volume_targets, ROWS)
    _write_integration_note(measured)
    for path in ("slow", "direct"):
        item = measured[path]
        assert item["row_count"] == ROWS, item
        assert item["inserted"] == ROWS, item
        assert item["qty_min"] == 1, item
        assert item["qty_max"] == ROWS, item
        assert item["peak_rss_bytes"] > 0, item
        assert item["durations_sec"], item
    assert measured["slow"]["note_kept"] == ROWS, measured["slow"]
    assert measured["direct"]["note_null"] == ROWS, measured["direct"]
    assert {"query", "batch", "fields", "write"} <= set(measured["slow"]["durations_sec"])
    assert {"query", "write"} <= set(measured["direct"]["durations_sec"])
