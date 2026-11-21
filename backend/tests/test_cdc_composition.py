"""Offline schema and mounted adapter contracts for integrated CDC changes."""

import ast
import importlib
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from backend.main import app


ROOT = Path(__file__).resolve().parents[2]


def test_mirror_management_is_mounted_in_main():
    paths = app.openapi()["paths"]
    assert set(paths["/mirrors"]) == {"get"}
    assert {"get", "patch", "delete"} <= paths["/mirrors/{mirror_id}"].keys()
    assert "post" in paths["/mirrors/{mirror_id}/recovery-requests"]


def test_alembic_discovers_every_mirror_owner_model():
    tree = ast.parse((ROOT / "backend/alembic/env.py").read_text())
    modules = {alias.name for node in tree.body if isinstance(node, ast.Import) for alias in node.names}
    expected = {
        "backend.metadata.mirrors.models": {"source_mirrors", "source_mirror_operations"},
        "backend.metadata.mirrors.history_models": {"source_mirror_history_gates", "source_mirror_history_invalidations"},
        "backend.metadata.mirrors.recovery_store": {"source_mirror_recoveries"},
        "backend.admin.notifications.models": {"notification_channel", "notification_events"},
    }
    from backend.core.db import Base

    for module, tables in expected.items():
        assert module in modules
        importlib.import_module(module)
        assert tables <= Base.metadata.tables.keys()


def test_migration_chain_and_checkpoint_legacy_backfill(monkeypatch):
    config = Config()
    config.set_main_option("script_location", str(ROOT / "backend/alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["0102_standalone_source_mirrors"]
    revisions = list(script.walk_revisions("0092_job_delayed_recovery"))
    assert [revision.revision for revision in revisions] == [
        "0102_standalone_source_mirrors", "0101_channel_pin_retention",
        "0100_mirror_references", "0099_channel_mirror_runs", "0098_mirror_checkpoints", "0097_mirror_recovery", "0096_mirror_history",
        "0095_mirror_management", "0094_foundation_notifications", "0093_source_capture_control",
        "0092_job_delayed_recovery",
    ]
    migration = importlib.import_module("backend.alembic.versions.0098_mirror_checkpoints")
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE channel_checkpoints (channel_id TEXT, node_id TEXT, stream TEXT, position_xact BIGINT, position_seq BIGINT, updated_at TEXT, PRIMARY KEY(channel_id,node_id,stream))"))
        connection.execute(text("INSERT INTO channel_checkpoints VALUES ('c','n','e',7,3,'now')"))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        assert connection.execute(text("SELECT stream_kind, history_epoch, source_ids, position_xact, position_seq FROM channel_checkpoints")).one() == ("entity", None, None, 7, 3)
        migration.downgrade()
        assert {column["name"] for column in inspect(connection).get_columns("channel_checkpoints")} == {"channel_id", "node_id", "stream", "position_xact", "position_seq", "updated_at"}
    engine.dispose()
