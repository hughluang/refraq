"""Dataset Query streams a registered Source. Live engines are optional."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text

from backend.channel.nodes import list_node_types
from backend.channel.nodes.volume.dataset_query import NODE_TYPE
from backend.tests.channel_hooks_fake import FakeHooks
from backend.tests.entity_pg import bootstrapped_entity_database

_MAINTENANCE = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)
_WHEN = datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def test_dataset_query_describes_a_source_stream() -> None:
    summary = NODE_TYPE.summary
    description = NODE_TYPE.description
    assert len([part for part in re.split(r"[.?!]", summary.strip()) if part.strip()]) == 1
    assert len(summary) <= 160
    assert len([part for part in re.split(r"[.?!]", description.strip()) if part.strip()]) >= 2
    lowered = description.lower()
    assert "read-only" in lowered
    assert "sql server" in lowered
    assert "snapshot" in lowered
    assert "fails this node" not in lowered


def _execute(type_id: str):
    return next(item.execute for item in list_node_types() if item.type_id == type_id)


def _postgres_available() -> bool:
    try:
        engine = create_engine(_MAINTENANCE)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


@pytest.fixture
def entity_db(monkeypatch: pytest.MonkeyPatch):
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")
    with bootstrapped_entity_database(_MAINTENANCE, "refraq_sstream") as urls:
        monkeypatch.setenv("ENTITY_DATABASE_URL", urls.owner_url)
        monkeypatch.setenv("ENTITY_READER_DATABASE_URL", urls.reader_url)
        monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
        from backend.admin.system_parameters import reset_parameter_registry
        from backend.channel.dataset_registry import reset_dataset_store
        from backend.core.config import reset_settings_cache
        from backend.entity.entity_db import reset_entity_engine
        from backend.worker.parameters import assemble_system_parameters

        reset_settings_cache()
        reset_entity_engine()
        assemble_system_parameters()
        reset_dataset_store()
        try:
            yield
        finally:
            reset_dataset_store()
            reset_parameter_registry()
            reset_entity_engine()
            reset_settings_cache()


def _plant_postgresql_source() -> None:
    from backend.core.time import utc_now
    from backend.metadata.sources.store import SourceRecord, get_source_store

    now = utc_now()
    get_source_store().create_source(
        SourceRecord(
            id="src_live",
            key="live",
            locator_key="src/postgresql/live",
            name="Live",
            kind="database",
            status="active",
            description=None,
            engine="postgresql",
            access_ciphertext="sealed",
            access_updated_at=now,
            created_at=now,
            updated_at=now,
        )
    )


class _Stream:
    def __init__(self, columns: list[object], chunks) -> None:
        self.columns = columns
        self.chunks = chunks

    def close(self) -> None:
        closer = getattr(self.chunks, "close", None)
        if closer is not None:
            closer()


@pytest.mark.integration
def test_dataset_query_streams_a_source_without_loading_every_row(
    entity_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    from decimal import Decimal

    from backend.channel.dataset_registry import DatasetRegistry, get_dataset_store
    from backend.channel.nodes.volume import materialize
    from backend.metadata.connectors.base import SourceEndpoint, StreamColumn
    from backend.metadata.connectors.runtime import PreparedEngine
    from backend.metadata.type_mappings.seeds import ensure_product_type_mappings
    from backend.metadata.type_mappings.store import get_type_mapping_store

    ensure_product_type_mappings()
    _plant_postgresql_source()
    calls: list[int] = []
    rows = [(index, Decimal("1.50"), _WHEN, "k") for index in range(1, 1002)]

    class _Connector:
        engine = "postgresql"

        def stream_statement(self, endpoint, sql, *, chunk_rows, deadline):
            del endpoint, deadline
            assert sql == "SELECT n, qty, ts, tag FROM probe"
            calls.append(chunk_rows)

            def chunks():
                for start in range(0, len(rows), chunk_rows):
                    yield [list(row) for row in rows[start : start + chunk_rows]]

            return _Stream(
                [
                    StreamColumn("n", "integer"),
                    StreamColumn("qty", "numeric(12,2)"),
                    StreamColumn("ts", "timestamp with time zone"),
                    StreamColumn("tag", "refraq_stream_probe"),
                ],
                chunks(),
            )

    def prepare(*, engine: str, access: dict[str, object]) -> PreparedEngine:
        del access
        assert engine == "postgresql"
        endpoint = SourceEndpoint(
            engine="postgresql",
            host="db.example",
            port=5432,
            username="reader",
            password="secret",
            database_name="app",
            schema_filter="public",
        )
        return PreparedEngine(connector=_Connector(), endpoint=endpoint)

    monkeypatch.setattr("backend.metadata.source_statements.decrypt_access_blob", lambda _blob: {})
    monkeypatch.setattr("backend.metadata.source_statements.prepare", prepare)
    result = _execute("volume.dataset_query")(
        {
            "id": "nd_query",
            "type": "volume.dataset_query",
            "config": {
                "source": {"kind": "source", "source_id": "src_live"},
                "sql": "SELECT n, qty, ts, tag FROM probe",
            },
        },
        FakeHooks(run_id="job_source_stream"),
    )
    assert result.status == "succeeded", result.error_message
    assert calls == [materialize._CHUNK_ROWS]
    assert result.output["count"] == 1001
    assert result.output["dataset"]["columns"] == [
        {
            "name": "n",
            "type": "integer",
            "temporal_kind": None,
            "precision": None,
            "nullable": None,
        },
        {
            "name": "qty",
            "type": "decimal",
            "temporal_kind": None,
            "precision": None,
            "nullable": None,
        },
        {
            "name": "ts",
            "type": "timestamp",
            "temporal_kind": "timestamp_with_time_zone",
            "precision": None,
            "nullable": None,
        },
        {
            "name": "tag",
            "type": "unknown",
            "temporal_kind": None,
            "precision": None,
            "nullable": None,
        },
    ]
    stored = get_dataset_store().get(result.output["dataset"]["dataset_id"])
    assert stored is not None
    assert [column["type"] for column in stored.columns] == [
        "bigint",
        "numeric(12,2)",
        "timestamp with time zone",
        "text",
    ]
    store = get_type_mapping_store()
    assert store.get_by_key("postgresql", "numeric(12,2)") is None
    assert store.get_by_key("postgresql", "numeric").normalized_type == "decimal"
    probe = store.get_by_key("postgresql", "refraq_stream_probe")
    assert probe is not None
    assert probe.origin == "job"
    assert probe.normalized_type == "unknown"
    page = DatasetRegistry(get_dataset_store()).read_page(
        result.output["dataset"]["dataset_id"], after_ord=1000, limit=1
    )
    assert page[0]["n"] == 1001
    assert page[0]["qty"] == Decimal("1.50")
    assert page[0]["tag"] == "k"


def _bind_stream(monkeypatch: pytest.MonkeyPatch, stream_statement) -> None:
    from backend.metadata.connectors.base import SourceEndpoint
    from backend.metadata.connectors.runtime import PreparedEngine

    _plant_postgresql_source()

    class _Connector:
        engine = "postgresql"

        def stream_statement(self, endpoint, sql, *, chunk_rows, deadline):
            return stream_statement(endpoint, sql, chunk_rows=chunk_rows, deadline=deadline)

    def prepare(*, engine: str, access: dict[str, object]) -> PreparedEngine:
        del access
        assert engine == "postgresql"
        endpoint = SourceEndpoint(
            engine="postgresql",
            host="db.example",
            port=5432,
            username="reader",
            password="secret",
            database_name="app",
            schema_filter="public",
        )
        return PreparedEngine(connector=_Connector(), endpoint=endpoint)

    monkeypatch.setattr("backend.metadata.source_statements.decrypt_access_blob", lambda _blob: {})
    monkeypatch.setattr("backend.metadata.source_statements.prepare", prepare)


def _source_node(*, timeout: int = 30) -> dict:
    config: dict = {
        "source": {"kind": "source", "source_id": "src_live"},
        "sql": "SELECT n FROM probe",
    }
    if timeout != 300:
        config["statement_timeout_sec"] = timeout
    return {"id": "nd_query", "type": "volume.dataset_query", "config": config}


def _relations() -> list[str]:
    from backend.entity.datasets import list_dataset_relations

    return list_dataset_relations()


@pytest.mark.integration
def test_dataset_query_times_out_before_the_first_source_chunk(
    entity_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def monotonic() -> float:
        calls["n"] += 1
        return 0.0 if calls["n"] == 1 else 1000.0

    monkeypatch.setattr(
        "backend.channel.nodes.volume.dataset_query.time.monotonic", monotonic
    )
    opened = {"n": 0}

    def stream_statement(endpoint, sql, *, chunk_rows, deadline):
        del endpoint, sql, chunk_rows, deadline
        opened["n"] += 1
        raise AssertionError("source was opened")

    _bind_stream(monkeypatch, stream_statement)
    result = _execute("volume.dataset_query")(_source_node(), FakeHooks(run_id="job_timeout"))
    assert opened["n"] == 0
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_NODE_FAILED"
    assert result.error_message == "Dataset Query exceeded the statement timeout"
    assert _relations() == []


@pytest.mark.integration
def test_dataset_query_stops_between_source_chunks_at_the_deadline(
    entity_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.metadata.connectors.base import StreamColumn

    clock = {"now": 0.0}
    monkeypatch.setattr(
        "backend.channel.nodes.volume.dataset_query.time.monotonic",
        lambda: clock["now"],
    )
    pulled: list[int] = []

    def stream_statement(endpoint, sql, *, chunk_rows, deadline):
        del endpoint, sql, chunk_rows, deadline

        def chunks():
            clock["now"] = 10_000.0
            yield [[1]]
            pulled.append(2)
            yield [[2]]

        return _Stream([StreamColumn("n", "integer")], chunks())

    _bind_stream(monkeypatch, stream_statement)
    result = _execute("volume.dataset_query")(_source_node(), FakeHooks(run_id="job_between"))
    assert pulled == []
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_NODE_FAILED"
    assert result.error_message == "Dataset Query exceeded the statement timeout"
    assert _relations() == []


@pytest.mark.integration
def test_dataset_query_stops_between_source_chunks_when_cancelled(
    entity_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.channel.nodes.volume.dataset_query import _StreamHalted
    from backend.metadata.connectors.base import StreamColumn

    hooks = FakeHooks(run_id="job_cancel")
    pulled: list[int] = []

    def stream_statement(endpoint, sql, *, chunk_rows, deadline):
        del endpoint, sql, chunk_rows, deadline

        def chunks():
            hooks.cancel_after = "nd_query"
            yield [[1]]
            pulled.append(2)
            yield [[2]]

        return _Stream([StreamColumn("n", "integer")], chunks())

    _bind_stream(monkeypatch, stream_statement)
    with pytest.raises(_StreamHalted, match="^cancelled$"):
        _execute("volume.dataset_query")(_source_node(), hooks)
    assert pulled == []
    assert _relations() == []


@pytest.mark.integration
def test_dataset_query_stops_between_source_chunks_when_superseded(
    entity_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.channel.nodes.volume.dataset_query import _StreamHalted
    from backend.metadata.connectors.base import StreamColumn

    class _Hooks(FakeHooks):
        def __init__(self) -> None:
            super().__init__(run_id="job_supersede")
            self.stop = False

        def superseded(self) -> bool:
            return self.stop

    hooks = _Hooks()
    pulled: list[int] = []

    def stream_statement(endpoint, sql, *, chunk_rows, deadline):
        del endpoint, sql, chunk_rows, deadline

        def chunks():
            hooks.stop = True
            yield [[1]]
            pulled.append(2)
            yield [[2]]

        return _Stream([StreamColumn("n", "integer")], chunks())

    _bind_stream(monkeypatch, stream_statement)
    with pytest.raises(_StreamHalted, match="^superseded$"):
        _execute("volume.dataset_query")(_source_node(), hooks)
    assert pulled == []
    assert _relations() == []


@pytest.mark.integration
def test_dataset_query_returns_a_source_database_error_without_retry(
    entity_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.metadata.connectors.base import StreamColumn

    calls = {"n": 0}

    def stream_statement(endpoint, sql, *, chunk_rows, deadline):
        del endpoint, sql, chunk_rows, deadline
        calls["n"] += 1

        def chunks():
            raise RuntimeError("ORA-01555: snapshot too old")
            yield [[1]]

        return _Stream([StreamColumn("n", "integer")], chunks())

    _bind_stream(monkeypatch, stream_statement)
    result = _execute("volume.dataset_query")(_source_node(), FakeHooks(run_id="job_ora"))
    assert calls["n"] == 1
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_NODE_FAILED"
    assert result.error_message == "ORA-01555: snapshot too old"
    assert _relations() == []


@pytest.mark.integration
def test_dataset_query_checks_capacity_after_each_source_chunk(
    entity_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.metadata.connectors.base import StreamColumn

    monkeypatch.setattr("backend.channel.dataset_registry._limit_bytes", lambda: 1)
    pulled: list[int] = []

    def stream_statement(endpoint, sql, *, chunk_rows, deadline):
        del endpoint, sql, chunk_rows, deadline

        def chunks():
            yield [[1]]
            pulled.append(2)
            yield [[2]]

        return _Stream([StreamColumn("n", "integer")], chunks())

    _bind_stream(monkeypatch, stream_statement)
    result = _execute("volume.dataset_query")(_source_node(), FakeHooks(run_id="job_quota"))
    assert pulled == []
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_DATASET_QUOTA_EXCEEDED"
    assert _relations() == []


_LIVE_ENVS = (
    "REFRAQ_TEST_PG_SOURCE_ID",
    "REFRAQ_TEST_ORACLE_SOURCE_ID",
    "REFRAQ_TEST_MSSQL_SOURCE_ID",
)
_LIVE_SQL = {
    "postgresql": (
        "SELECT n::integer AS n, n::numeric(12,2) AS qty "
        "FROM generate_series(1, 1001) AS n"
    ),
    "oracle": (
        "SELECT LEVEL AS n, CAST(LEVEL AS NUMBER(12, 2)) AS qty "
        "FROM dual CONNECT BY LEVEL <= 1001"
    ),
    "mssql": (
        "SELECT n, CAST(n AS decimal(12, 2)) AS qty FROM ("
        "SELECT TOP 1001 ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS n "
        "FROM sys.all_columns AS a CROSS JOIN sys.all_columns AS b"
        ") AS generated"
    ),
}
_LIVE_TIMEOUT_SQL = {
    "postgresql": "SELECT pg_sleep(5) AS slept",
    "oracle": "SELECT LEVEL AS n FROM dual CONNECT BY LEVEL <= 100000000",
    "mssql": (
        "SELECT COUNT(*) AS n FROM sys.all_columns AS a "
        "CROSS JOIN sys.all_columns AS b CROSS JOIN sys.all_columns AS c"
    ),
}
_LIVE_N_TYPE = {"postgresql": "integer", "oracle": "decimal", "mssql": "integer"}


@pytest.fixture(params=_LIVE_ENVS)
def live_source(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """Registered Source plus a throwaway entity database. Skips when the id is unset."""
    env_name = request.param
    source_id = os.environ.get(env_name)
    if not source_id:
        pytest.skip(f"{env_name} is unset")
    from backend.core.config import Settings

    loaded = Settings()
    if not loaded.database_url:
        pytest.skip("platform database URL is unset")
    if not loaded.refraq_secrets_master_key:
        pytest.skip("REFRAQ_SECRETS_MASTER_KEY is unset")
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")

    from backend.admin.system_parameters import reset_parameter_registry
    from backend.channel.dataset_registry import reset_dataset_store
    from backend.core.config import reset_settings_cache
    from backend.core.db import reset_db_singletons
    from backend.entity.entity_db import reset_entity_engine
    from backend.metadata.sources.store import SqlSourceStore
    from backend.metadata.sources.store import reset_source_store
    from backend.metadata.type_mappings.seeds import ensure_product_type_mappings
    from backend.worker.parameters import assemble_system_parameters

    def _release() -> None:
        reset_dataset_store()
        reset_parameter_registry()
        reset_entity_engine()
        reset_source_store()
        reset_db_singletons()

    try:
        with bootstrapped_entity_database(_MAINTENANCE, "refraq_slive") as urls:
            monkeypatch.setenv("ENTITY_DATABASE_URL", urls.owner_url)
            monkeypatch.setenv("ENTITY_READER_DATABASE_URL", urls.reader_url)
            monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
            monkeypatch.setenv("DATABASE_URL", loaded.database_url)
            monkeypatch.setenv(
                "REFRAQ_SECRETS_MASTER_KEY", loaded.refraq_secrets_master_key
            )
            reset_settings_cache()
            reset_db_singletons()
            reset_source_store()
            reset_entity_engine()
            assemble_system_parameters()
            reset_dataset_store()
            ensure_product_type_mappings()
            store = SqlSourceStore()
            monkeypatch.setattr(
                "backend.metadata.source_statements.get_source_store", lambda: store
            )
            record = store.get_source(source_id)
            if record is None or not record.engine:
                pytest.skip(f"{env_name} does not resolve")
            try:
                yield source_id, record.engine
            finally:
                _release()
    finally:
        monkeypatch.undo()
        reset_settings_cache()
        _release()


def _live_node(source_id: str, sql: str, *, timeout: int = 30) -> dict:
    return {
        "id": "nd_query",
        "type": "volume.dataset_query",
        "config": {
            "source": {"kind": "source", "source_id": source_id},
            "sql": sql,
            "statement_timeout_sec": timeout,
        },
    }


@pytest.mark.integration
def test_dataset_query_streams_a_registered_source(live_source) -> None:
    from decimal import Decimal

    from backend.channel.dataset_registry import DatasetRegistry, get_dataset_store

    source_id, engine = live_source
    sql = _LIVE_SQL[engine]
    result = _execute("volume.dataset_query")(
        _live_node(source_id, sql), FakeHooks(run_id="job_live_stream")
    )
    assert result.status == "succeeded", result.error_message
    assert result.output["count"] == 1001
    columns = {column["name"]: column["type"] for column in result.output["dataset"]["columns"]}
    assert columns["n"] == _LIVE_N_TYPE[engine]
    assert columns["qty"] == "decimal"
    stored = get_dataset_store().get(result.output["dataset"]["dataset_id"])
    assert stored is not None
    physical = {column["name"]: column["type"] for column in stored.columns}
    assert physical["qty"] == "numeric(12,2)"
    page = DatasetRegistry(get_dataset_store()).read_page(
        result.output["dataset"]["dataset_id"], after_ord=1000, limit=1
    )
    assert int(page[0]["n"]) == 1001
    assert Decimal(str(page[0]["qty"])) == Decimal("1.50")


@pytest.mark.integration
def test_dataset_query_live_source_times_out_during_the_read(live_source) -> None:
    source_id, engine = live_source
    result = _execute("volume.dataset_query")(
        _live_node(source_id, _LIVE_TIMEOUT_SQL[engine], timeout=1),
        FakeHooks(run_id="job_live_timeout"),
    )
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_NODE_FAILED"
    assert _relations() == []


@pytest.mark.integration
def test_dataset_query_live_source_stops_between_chunks_at_the_deadline(
    live_source, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    from backend.channel.dataset_registry import get_dataset_store

    source_id, engine = live_source
    real = time.monotonic
    start = real()

    def monotonic() -> float:
        if get_dataset_store().used_bytes() > 0:
            return start + 100_000
        return real()

    monkeypatch.setattr(
        "backend.channel.nodes.volume.dataset_query.time.monotonic", monotonic
    )
    result = _execute("volume.dataset_query")(
        _live_node(source_id, _LIVE_SQL[engine]),
        FakeHooks(run_id="job_live_between"),
    )
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_NODE_FAILED"
    assert result.error_message == "Dataset Query exceeded the statement timeout"
    assert _relations() == []


@pytest.mark.integration
def test_dataset_query_live_source_stops_between_chunks_when_cancelled(
    live_source,
) -> None:
    from backend.channel.dataset_registry import get_dataset_store
    from backend.channel.nodes.volume.dataset_query import _StreamHalted

    source_id, engine = live_source

    class _Hooks(FakeHooks):
        def cancelled(self) -> bool:
            return get_dataset_store().used_bytes() > 0

    with pytest.raises(_StreamHalted, match="^cancelled$"):
        _execute("volume.dataset_query")(
            _live_node(source_id, _LIVE_SQL[engine]),
            _Hooks(run_id="job_live_cancel"),
        )
    assert _relations() == []
