"""Offline restricted-engine assembly, catalog and run-migration contracts."""

import importlib
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

from backend.admin.console_modules import build_module_identities, build_navigation
from backend.core.config import MirrorTargetSettings, Settings
from backend.metadata.mirrors import composition
from backend.metadata.mirrors.reads import Reads
from backend.metadata.mirrors.service import MirrorError


def policy(**changes):
    values = dict(
        gateway_url="postgresql+psycopg://refraq_mirror_gateway:private@target/mirrors?sslmode=verify-full",
        applier_url="postgresql+psycopg://refraq_mirror_applier:private@target/mirrors?sslmode=verify-full",
        timeout_ms=1200, connect_timeout_seconds=2,
    )
    return MirrorTargetSettings(**(values | changes))


def settings(target=None, *, backend="persistent"):
    return Settings(_env_file=None, REFRAQ_STORE_BACKEND=backend,
                    DATABASE_URL="postgresql+psycopg://manager:private@management/refraq",
                    REDIS_URL="redis://unused", REFRAQ_MIRROR_TARGET=target)


def test_absent_config_and_memory_never_construct_engine(monkeypatch):
    monkeypatch.setattr(composition, "create_engine", lambda *a, **k: pytest.fail("Unexpected target connection"))
    assert composition.compose_mirrors(settings()) is None
    assert composition.compose_mirrors(settings(policy(), backend="memory")) is None


@pytest.mark.parametrize("changes", [
    {"gateway_url": "postgresql+psycopg://owner:private@target/mirrors?sslmode=verify-full"},
    {"applier_url": "postgresql+psycopg://refraq_mirror_applier:private@other/mirrors?sslmode=verify-full"},
    {"gateway_url": "postgresql+psycopg://refraq_mirror_gateway:private@target/mirrors?sslmode=require"},
    {"gateway_url": "postgresql+psycopg://refraq_mirror_gateway:private@target/mirrors?sslmode=verify-full&options=-crole=owner"},
    {"timeout_ms": 0}, {"connect_timeout_seconds": 0},
])
def test_invalid_policy_fails_without_secret_in_error(changes):
    with pytest.raises(ValidationError) as caught:
        policy(**changes)
    assert "private" not in str(caught.value)


class Connection:
    connection = None

    def __init__(self):
        self.connection = self
        self.driver_connection = self


class Engine:
    def __init__(self):
        self.disposed = False

    @contextmanager
    def connect(self):
        yield Connection()

    def dispose(self):
        self.disposed = True


def test_validated_real_reads_and_history_only(monkeypatch):
    engines, roles, options = [], [], []

    def create(url, **kwargs):
        engine = Engine()
        engines.append(engine)
        options.append(kwargs)
        return engine

    monkeypatch.setattr(composition, "create_engine", create)
    monkeypatch.setattr(composition, "validate_target", lambda connection, *, expected_role: roles.append(expected_role))
    monkeypatch.setattr(composition.SqlHistoryTarget, "validate", lambda self: None)
    adapters = composition.compose_mirrors(settings(policy()))
    assert type(adapters.reads) is Reads
    assert adapters.reads.authorize_source_read is composition.authorize_source_data
    assert roles == ["refraq_mirror_gateway", "refraq_mirror_applier"]
    assert all(item["hide_parameters"] and not item["echo"] for item in options)
    assert all(item["connect_args"]["connect_timeout"] == 2 for item in options)
    assert "statement_timeout=1200" in options[0]["connect_args"]["options"]
    with pytest.raises(MirrorError):
        adapters.reads.release_run_pins(run_id="run", terminal_proof={"done": True})
    adapters.close()
    assert all(engine.disposed for engine in engines)
    with pytest.raises(MirrorError):
        with adapters.gateway.begin():
            pytest.fail("Closed target must stay unavailable")


def test_invalid_target_disposes_and_redacts(monkeypatch):
    engine = Engine()
    monkeypatch.setattr(composition, "create_engine", lambda *a, **k: engine)

    def invalid(*args, **kwargs):
        raise ValueError("private credential row image")

    monkeypatch.setattr(composition, "validate_target", invalid)
    with pytest.raises(MirrorError) as caught:
        composition.compose_mirrors(settings(policy()))
    assert engine.disposed
    assert caught.value.code == "MIRROR_READ_UNAVAILABLE"
    assert "private" not in str(caught.value)


def test_bootstrap_and_history_version_checks_are_actually_executed(monkeypatch):
    calls = []

    class Cursor:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

        def scalar_one(self):
            return self.row[0]

    class ValidConnection(Connection):
        def __init__(self, role):
            super().__init__()
            self.role = role

        def execute(self, statement, parameters=None):
            sql = str(statement)
            calls.append(sql)
            if sql == "SELECT current_user":
                return Cursor((self.role,))
            if "FROM pg_roles" in sql:
                return Cursor((False,) * 5)
            return Cursor((1,))

    class ValidEngine(Engine):
        def __init__(self, role):
            super().__init__()
            self.connection = ValidConnection(role)

        @contextmanager
        def connect(self):
            yield self.connection

        begin = connect

    roles = iter(("refraq_mirror_gateway", "refraq_mirror_applier"))
    monkeypatch.setattr(composition, "create_engine", lambda *a, **k: ValidEngine(next(roles)))
    adapters = composition.compose_mirrors(settings(policy()))
    assert calls.count("SELECT current_user") == 2
    assert calls.count("SELECT source_mirror_state.target_version()") == 2
    assert "SELECT source_mirror_state.history_version()" in calls
    adapters.close()


def test_serving_sql_errors_do_not_escape():
    class Broken(Engine):
        @contextmanager
        def begin(self):
            raise OperationalError("private row SQL", {"secret": "private"}, Exception("private driver"))
            yield

    with pytest.raises(MirrorError) as caught:
        with composition._ServingEngine(Broken()).begin():
            pass
    assert "private" not in str(caught.value)
    assert caught.value.__suppress_context__


def test_catalog_matches_frontend_and_permission_filtered_navigation():
    identities = {item.id: item for item in build_module_identities()}
    mirror = identities["mirrors"]
    assert mirror.icon == "database"
    assert asdict(mirror.routes) == dict(list="/console/mirrors", show="/console/mirrors/:id", create=None, edit=None, aliases=())
    assert mirror.actions.list == mirror.actions.show == "mirror:read"
    assert mirror.actions.edit == mirror.actions.delete == "mirror:write"
    assert identities["settings"].routes.aliases[0].path == "/console/settings/notification-channel"
    assert identities["settings"].routes.aliases[0].action == "list"
    assert not build_navigation(["mirror:write"])
    groups = build_navigation(["mirror:read"])
    assert groups[0].id == "operations"
    assert groups[0].modules[0].id == "mirrors"
    generated = (Path(__file__).resolve().parents[2] / "frontend/src/features/console/module-identity/generated-catalog.ts").read_text()
    assert 'id: "mirrors"' in generated
    assert 'show: "/console/mirrors/:id"' in generated


def test_run_migration_preserves_legacy_without_identity_backfill(monkeypatch):
    migration = importlib.import_module("backend.alembic.versions.0099_channel_mirror_runs")
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE channel_runs (job_id TEXT PRIMARY KEY)"))
        connection.execute(text("INSERT INTO channel_runs VALUES ('old')"))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        assert connection.execute(text("SELECT job_id, mirror_execution_user_id, mirror_state FROM channel_runs")).one() == ("old", None, None)
        columns = {column["name"]: column for column in inspect(connection).get_columns("channel_runs")}
        assert columns["mirror_execution_user_id"]["nullable"]
        assert columns["mirror_state"]["nullable"]
        migration.downgrade()
        assert connection.execute(text("SELECT * FROM channel_runs")).one() == ("old",)
    engine.dispose()
