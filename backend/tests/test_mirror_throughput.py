"""Measured byte rates preserve missing evidence, interval coverage and history."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from importlib import import_module
from types import SimpleNamespace

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
import httpx
import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.metadata.mirrors import diagnostics
import backend.metadata.mirrors.models  # noqa: F401
from backend.metadata.mirrors.diagnostic_schemas import MirrorSample, SourceReceipt
from backend.metadata.mirrors.diagnostic_store import DiagnosticRow, DiagnosticStore
from backend.metadata.mirrors.errors import MirrorError
from backend.metadata.mirrors.throughput import ThroughputResponse, read_throughput
from backend.metadata.mirrors.throughput_store import ThroughputRow, row_value


@pytest.fixture(params=["memory", "sql"])
def history(request):
    engine = None
    if request.param == "sql":
        engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        migration = import_module("backend.alembic.versions.0106_mirror_throughput")
        with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        DiagnosticRow.__table__.create(engine)

    @contextmanager
    def transaction():
        with Session(engine) as session, session.begin():
            yield session
    store = DiagnosticStore(memory=engine is None, transaction=transaction)
    yield store
    if engine is not None:
        with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert "source_mirror_throughput" not in inspect(engine).get_table_names()
        engine.dispose()


@pytest.fixture
def fleet(history):
    now = datetime(2026, 11, 24, 12, 0, 30, tzinfo=UTC)
    authority = dict(binding_id="binding", runtime_instance_id="runtime", owner_epoch=1,
                     capture_generation="capture", control_revision=2, credential_revision=1)
    mirrors = [dict(id="first", source_id="sales"), dict(id="second", source_id="payments"),
               dict(id="missing", source_id="sales")]
    bindings = {"sales": authority, "payments": dict(authority, runtime_instance_id=None)}
    return SimpleNamespace(now=now, authority=authority, mirrors=mirrors, bindings=bindings, store=history,
                           read_scope=lambda: (mirrors, bindings))


def record(fleet, mirror_id="first", *, end=None, seconds=10, **metrics):
    end = end or fleet.now - timedelta(seconds=10)
    source_id = next(m["source_id"] for m in fleet.mirrors if m["id"] == mirror_id)
    sample = MirrorSample(mirror_id=mirror_id, capture_generation="capture", generation_id="generation",
                          interval_start=end - timedelta(seconds=seconds), interval_end=end,
                          observed_at=end, valid_until=end + timedelta(seconds=60), **metrics)
    diagnostics.record_source(source_id, fleet.bindings[source_id], SourceReceipt(samples=[sample]),
                              store=fleet.store, now=fleet.now, round_id=mirror_id + end.isoformat())
    return sample


def view(fleet, **kwargs):
    value = read_throughput(store=fleet.store, read_scope=fleet.read_scope, now=fleet.now, **kwargs)
    ThroughputResponse.model_validate(value)
    return value


def stored_bins(store):
    if store.memory:
        return [row for bins in store.throughput.values() for row in bins.values()]
    with store.transaction() as session:
        return [row_value(row) for row in session.scalars(select(ThroughputRow))]


def test_rates_sum_measured_intervals_without_filling_missing_values(fleet):
    record(fleet, captured_bytes=4_000_000, committed_bytes=1_000_000, seconds=2)
    record(fleet, "second", captured_bytes=100_000_000, seconds=10)
    result = view(fleet)
    assert len(result["points"]) == 24 and result["hours"] == 6
    received, committed = result["points"][-1]["received"], result["points"][-1]["committed"]
    assert (received["value"], received["sampled"], received["missing"], received["measured_seconds"]) == (12, 2, 1, 12)
    assert (committed["value"], committed["sampled"], committed["missing"]) == (0.5, 1, 2)
    assert received["interval_start"] != committed["interval_start"]
    assert all(point["received"]["value"] is None for point in result["points"][:-1])
    record(fleet, end=fleet.now - timedelta(minutes=20), committed_bytes=0)
    idle = next(point["committed"] for point in view(fleet)["points"] if point["committed"]["value"] == 0)
    assert idle["sampled"] == 1 and idle["missing"] == 2


def test_history_retains_lineage_and_expired_intervals_after_authority_change(fleet):
    old = fleet.now - timedelta(hours=23, minutes=50)
    record(fleet, end=old, committed_bytes=5_000_000)
    fleet.bindings["sales"] = dict(fleet.authority, owner_epoch=7, capture_generation="replacement")
    result = view(fleet, hours=24)
    assert result["points"][0]["committed"]["value"] == 0.5
    assert all(point["committed"]["value"] is None for point in view(fleet, hours=6)["points"])
    rows = stored_bins(fleet.store)
    assert rows[0]["capture_generation"] == "capture" and rows[0]["authority"]["owner_epoch"] == "1"


def test_compaction_preserves_actual_duration_gaps_and_deduplicates_intervals(fleet):
    first_end = fleet.now - timedelta(seconds=50)
    record(fleet, end=first_end, seconds=5, committed_bytes=5_000_000)
    second_end = fleet.now - timedelta(seconds=35)
    record(fleet, end=second_end, seconds=5, committed_bytes=5_000_000)
    record(fleet, end=second_end, seconds=5, committed_bytes=5_000_000)
    record(fleet, end=second_end + timedelta(seconds=1), seconds=4, committed_bytes=100_000_000)
    metric = view(fleet)["points"][-1]["committed"]
    assert metric["value"] == 1 and metric["measured_seconds"] == 10
    assert metric["interval_start"].startswith("2026-11-24T11:59:35")
    assert metric["interval_end"].startswith("2026-11-24T11:59:55")
    rows = stored_bins(fleet.store)
    assert len(rows) == 1


def test_late_disjoint_interval_fills_a_compacted_gap_without_double_counting(fleet):
    record(fleet, end=fleet.now - timedelta(seconds=50), seconds=5, committed_bytes=5_000_000)
    record(fleet, end=fleet.now - timedelta(seconds=35), seconds=5, committed_bytes=5_000_000)
    record(fleet, end=fleet.now - timedelta(seconds=40), seconds=10, committed_bytes=10_000_000)
    record(fleet, end=fleet.now - timedelta(seconds=40), seconds=10, committed_bytes=10_000_000)
    metric = view(fleet)["points"][-1]["committed"]
    assert metric["value"] == 1 and metric["measured_seconds"] == 20


def test_late_observation_cannot_retain_intervals_outside_retention(fleet):
    end = fleet.now - timedelta(hours=26)
    sample = MirrorSample(mirror_id="first", capture_generation="capture", generation_id="generation",
                          interval_start=end - timedelta(seconds=10), interval_end=end,
                          observed_at=fleet.now, valid_until=fleet.now + timedelta(seconds=60), committed_bytes=1_000_000)
    fleet.store.record_throughput("sales", fleet.authority, sample, now=fleet.now)
    assert stored_bins(fleet.store) == []


@pytest.mark.parametrize("hours", [1, 6, 24])
def test_chart_bucket_boundaries_keep_observations_in_their_actual_point(fleet, hours):
    step = timedelta(hours=hours) / 24
    start = fleet.now - timedelta(hours=hours)
    record(fleet, end=start + step * 0.75, committed_bytes=10_000_000)
    record(fleet, "second", end=start + step, committed_bytes=20_000_000)
    record(fleet, "missing", end=start + step + timedelta(seconds=30), committed_bytes=30_000_000)
    points = view(fleet, hours=hours)["points"]
    assert points[0]["committed"]["value"] == 3
    assert points[1]["committed"]["value"] == 3
    assert all(point["committed"]["value"] is None for point in points[2:])


def test_scope_uses_current_mirror_bearing_sources_and_current_assignments(fleet):
    record(fleet, committed_bytes=10_000_000)
    record(fleet, "second", committed_bytes=30_000_000)
    result = view(fleet, source_id="sales")
    assert (result["source_count"], result["mirror_count"], result["points"][-1]["committed"]["value"]) == (1, 2, 1)
    assert view(fleet, runtime_id="unassigned")["points"][-1]["committed"]["value"] == 3
    fleet.bindings["sales"] = dict(fleet.authority, runtime_instance_id="new-runtime")
    assert view(fleet, runtime_id="new-runtime")["points"][-1]["committed"]["value"] == 1
    assert view(fleet, runtime_id="runtime")["mirror_count"] == 0
    fleet.bindings["no-mirrors"] = dict(fleet.authority)
    with pytest.raises(MirrorError):
        view(fleet, source_id="no-mirrors")


def test_future_samples_cannot_enter_history_or_latest_projection(fleet):
    with pytest.raises(ValueError, match="Future diagnostic sample"):
        record(fleet, end=fleet.now + timedelta(seconds=1), committed_bytes=1)
    assert fleet.store.all("sample") == {}
    assert all(point["committed"]["value"] is None for point in view(fleet)["points"])


def test_native_commit_byte_coverage_never_creates_received_bytes(monkeypatch):
    from backend.metadata.capture.diagnostics import RuntimeDiagnostics
    from backend.tests.test_mirror_diagnostics import policy

    store = DiagnosticStore(memory=True, transaction=None)
    now = datetime(2026, 11, 24, 12, tzinfo=UTC)
    monkeypatch.setattr("backend.metadata.capture.diagnostics.utc_now", lambda: now)
    collector = RuntimeDiagnostics(policy=policy(), runtimes=[], wait_seconds=5, store=store, read_scope=lambda: ([], {}))
    progress = dict(mirror_id="first", generation_id="generation", authority={}, processed_events=10,
                    processed_batches=1, processed_bytes=100, applied_offset=15, last_target_commit_at=None)
    collector._activity(progress, None, {"capture_generation": "capture"}, SourceReceipt(), set())
    now += timedelta(seconds=2)
    progress.update(processed_events=12, processed_batches=2, processed_bytes=300)
    receipt = SourceReceipt()
    collector._activity(progress, None, {"capture_generation": "capture"}, receipt, set())
    assert receipt.samples[0].committed_bytes == 200 and receipt.samples[0].captured_bytes is None
    now += timedelta(seconds=2)
    progress["processed_bytes"] = None
    receipt = SourceReceipt()
    collector._activity(progress, None, {"capture_generation": "capture"}, receipt, set())
    assert receipt.samples[0].committed_bytes is None


def test_throughput_route_requires_only_operations_permission_and_valid_window(fleet):
    import asyncio
    from backend.admin.deps import get_current_user
    from backend.admin.role_store import get_role_store
    from backend.core.errors import AppError
    from backend.main import app_error_handler
    from backend.metadata.mirrors.router import router

    app = FastAPI()
    app.state.mirror_diagnostics = fleet.store
    app.state.mirror_diagnostic_scope = fleet.read_scope
    app.include_router(router)
    app.add_exception_handler(AppError, app_error_handler)
    permissions = ["mirror:read"]
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="operator", role_id="role")
    app.dependency_overrides[get_role_store] = lambda: SimpleNamespace(get_by_id=lambda _: SimpleNamespace(key="custom", permissions=permissions))
    async def verify():
        async def clock_tick():
            # Keep this in-process loop responsive on hosts whose selector does
            # not wake reliably for AnyIO worker-thread completions.
            while True:
                await asyncio.sleep(0.01)
        tick = asyncio.create_task(clock_tick())
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                assert (await asyncio.wait_for(client.get("/mirror-throughput?source_id=sales&hours=24"), 5)).status_code == 200
                assert (await asyncio.wait_for(client.get("/mirror-throughput?hours=2"), 5)).status_code == 422
                permissions.clear()
                assert (await asyncio.wait_for(client.get("/mirror-throughput"), 5)).status_code == 403
        finally:
            tick.cancel()
    asyncio.run(verify())
