"""Fleet reads reconcile real filtered totals, triage and independent Source health."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from functools import partial
from threading import RLock
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.metadata.mirrors import diagnostics, fleet, service
from backend.metadata.mirrors.diagnostic_store import DiagnosticRow, DiagnosticStore
from backend.metadata.mirrors.fleet_schemas import FleetOverview, InventoryPage, RuntimeFleetPage, SourceFleetPage
from backend.metadata.mirrors.history_models import HistoryGateRow
from backend.metadata.mirrors.models import MirrorOperationRow, MirrorRow
from backend.metadata.mirrors.store import MemoryMirrorStore, SqlMirrorStore
from backend.metadata.models import CatalogObjectRow, SourceCaptureBindingRow, SourceRow

NOW = datetime(2026, 11, 24, 12, tzinfo=UTC)


def mirror(mid, source="s1", *, published=False, blocker=None, status="waiting", enabled=True):
    value = service._new(dict(source_id=source, source_key=source, source_name="Source " + source,
        object_id="o-" + mid, qualified_table="public." + mid, table_identity="o-" + mid))
    value.update(id=mid, enabled=enabled, status=status, published_generation_id="g-" + mid if published else None)
    if blocker:
        value["blocker"] = dict(cause=blocker, since=(NOW - timedelta(hours=4)).isoformat(), last_checked_at=NOW.isoformat())
    return value


def operation(value, *, kind="open", state="pending", age=1):
    return dict(id="op-" + value["id"], mirror_id=value["id"], kind=kind, state=state,
        control_revision=value["control"]["control_revision"], requested_at=(NOW - timedelta(hours=age)).isoformat(),
        observed_evidence_refs=[], fault_code=None)


@pytest.fixture(params=["memory", "sql"])
def data(request, monkeypatch):
    from backend.metadata.mirrors import store as mirror_store

    sources, objects, bindings = {}, {}, {}
    source_store = SimpleNamespace(capture_lock=RLock(), capture_bindings=bindings,
        list_sources=lambda: (list(sources.values()), len(sources)), get_source=sources.get)
    catalog = SimpleNamespace(get_object=objects.get)
    monkeypatch.setattr(mirror_store, "get_source_store", lambda: source_store)
    monkeypatch.setattr(mirror_store, "get_catalog_store", lambda: catalog)
    engine = None
    if request.param == "memory":
        storage = MemoryMirrorStore()
        telemetry = DiagnosticStore(memory=True, transaction=storage.transaction)
    else:
        engine = create_engine("sqlite://")
        for model in (SourceRow, CatalogObjectRow, MirrorRow, MirrorOperationRow, SourceCaptureBindingRow, DiagnosticRow, HistoryGateRow):
            model.__table__.create(engine)
        factory = sessionmaker(engine, expire_on_commit=False)
        storage = SqlMirrorStore()
        storage.transaction = factory.begin
        telemetry = DiagnosticStore(memory=False, transaction=factory.begin)
    service.bind_management(store=storage)

    def add_source(sid, runtime=None, *, credential=True, health="unobserved"):
        source = SimpleNamespace(id=sid, key=sid, name="Source " + sid, status="active",
            capture_credential_ciphertext="test-only" if credential else None, snapshot_window=None)
        sources[sid] = source
        authority = dict(source_id=sid, binding_id="b-" + sid, runtime_instance_id=runtime, owner_epoch=1,
            capture_generation="capture", control_revision=1, credential_revision=1)
        if runtime:
            bindings[sid] = authority
        if engine:
            with storage.transaction() as session:
                session.add(SourceRow(id=sid, key=sid, locator_key=sid, name=source.name, kind="database", status="active",
                    capture_credential_ciphertext=source.capture_credential_ciphertext, created_at=NOW, updated_at=NOW))
                if runtime:
                    session.add(SourceCaptureBindingRow(source_id=sid, binding_id="b-" + sid, state=authority))
        if health != "unobserved":
            window = dict(observed_at=NOW.isoformat(), valid_until=(NOW + timedelta(minutes=5)).isoformat())
            checks = {link: dict(outcome="healthy", **window) for link in diagnostics.LINKS}
            if health == "failed":
                checks["replication"].update(outcome="failed", error_code="REPLICATION_UNAVAILABLE")
            telemetry.update("source", sid, lambda _: dict(authority=diagnostics._identity(authority), checks=checks, history=[]))

    def add(value, *, size=100, rows=10, op=None):
        obj = SimpleNamespace(source_size_bytes=size, estimated_rows=rows)
        objects[value["object_id"]] = obj
        op = op or operation(value)
        if engine:
            with storage.transaction() as session:
                session.add(CatalogObjectRow(id=value["object_id"], source_id=value["source_id"], locator_key=value["object_id"],
                    object_type="table", schema_name="public", name=value["id"], source_size_bytes=size, estimated_rows=rows,
                    is_present=True, created_at=NOW, updated_at=NOW))
                session.add(MirrorRow(id=value["id"], source_id=value["source_id"], table_identity=value["table_identity"],
                    enabled=value["enabled"], effective_status=value["status"], state=deepcopy(value)))
                session.add(MirrorOperationRow(id=op["id"], mirror_id=value["id"], command=deepcopy(op)))
        else:
            storage.mirrors[value["id"]] = deepcopy(value)
            storage.operations[op["id"]] = deepcopy(op)

    dependencies = dict(store=telemetry, mirror_store=storage, source_store=source_store, catalog_store=catalog)
    result = SimpleNamespace(storage=storage, telemetry=telemetry, add_source=add_source, add=add, engine=engine,
                             dependencies=dependencies, source_store=source_store, catalog_store=catalog)
    yield result
    service.bind_management()
    if engine:
        engine.dispose()


def test_totals_and_inventory_share_four_evidence_based_buckets(data):
    data.add_source("s1", "runtime", health="failed")
    data.add_source("s2", credential=False)
    data.add_source("zero", "runtime")
    data.add(mirror("ready", published=True, status="ready"), op=operation(mirror("ready"), state="applied"))
    data.add(mirror("waiting"), size=None, rows=None)
    data.add(mirror("blocked", blocker="schema"))
    data.add(mirror("pending", enabled=False, status="disable_pending", published=True), op=operation(mirror("pending"), kind="disable"))
    stopped = mirror("stopped", enabled=False, status="disabled", published=True)
    stopped["control"].update(applied_revision=1, observed_at=NOW.isoformat(),
        stop_ack=dict(operation_id="op-stopped", source_operation_id="stop-source", observed_at=NOW.isoformat()))
    stop_op = operation(stopped, kind="disable", state="applied")
    stop_op["observed_evidence_refs"] = ["stop-source"]
    data.add(stopped, op=stop_op)
    data.add(mirror("prerequisite", source="s2"))
    overview = fleet.overview(**data.dependencies, now=NOW)
    FleetOverview.model_validate(overview)
    assert (overview["mirror_count"], overview["source_count"], overview["published_count"]) == (6, 2, 3)
    assert overview["source_size"] == dict(value=500, sampled=5, missing=1)
    assert {key: value["count"] for key, value in overview["states"].items()} == dict(synchronizing=1, copying=1, attention=3, stopped=1)
    assert overview["health"] == dict(failed=1, stale=0, unobserved=1, healthy=0)
    assert sum(overview["segments"]["replication"].values()) == 2
    assert overview["segments"]["storage"]["healthy"] == 1
    for state, value in overview["states"].items():
        result = fleet.inventory(**data.dependencies, now=NOW, grouped_state=state, limit=12)
        InventoryPage.model_validate(result)
        assert result["total"] == value["count"]
    stopped_page = fleet.inventory(**data.dependencies, now=NOW, grouped_state="stopped", published_only=True, limit=12)
    assert stopped_page["items"][0]["id"] == "stopped"


def test_search_facets_and_triage_apply_before_paging(data):
    data.add_source("s1", "runtime")
    for i in range(16):
        item = mirror("mirror_%02d" % i, published=i >= 8, blocker="schema" if i % 2 else "permission")
        item["blocker"]["since"] = (NOW - timedelta(hours=i + 1)).isoformat()
        data.add(item, size=i, rows=100 - i)
    first = fleet.inventory(**data.dependencies, now=NOW, grouped_state="attention", sort="priority", limit=12)
    assert first["total"] == 16
    assert [r["id"] for r in first["items"][:8]] == ["mirror_%02d" % i for i in range(7, -1, -1)]
    later = fleet.inventory(**data.dependencies, now=NOW, grouped_state="attention", sort="priority", limit=12, offset=12)
    assert len(later["items"]) == 4
    assert not set(r["id"] for r in first["items"]) & set(r["id"] for r in later["items"])
    filtered = fleet.inventory(**data.dependencies, now=NOW, grouped_state="attention", cause="schema", limit=12)
    assert filtered["total"] == 8
    assert filtered["cause_counts"]["schema"] == filtered["cause_counts"]["permission"] == 8
    assert fleet.inventory(**data.dependencies, now=NOW, q="MIRROR_15", limit=12)["total"] == 1
    assert fleet.inventory(**data.dependencies, now=NOW, q="%", limit=12)["total"] == 0
    assert fleet.inventory(**data.dependencies, now=NOW, sort="size", limit=1)["items"][0]["id"] == "mirror_15"


def test_source_and_runtime_health_filters_use_selected_segment(data):
    data.add_source("s1", "runtime-A", health="failed")
    data.add_source("s2", "runtime-A", health="healthy")
    data.add_source("s3")
    data.add_source("zero", "runtime-B", health="healthy")
    for sid in ("s1", "s2", "s3"):
        data.add(mirror("m-" + sid, source=sid))
    failed = fleet.sources(**data.dependencies, now=NOW, health="failed")
    SourceFleetPage.model_validate(failed)
    assert [s["id"] for s in failed["items"]] == ["s1"]
    storage = fleet.sources(**data.dependencies, now=NOW, segment="storage", health="healthy")
    assert [s["id"] for s in storage["items"]] == ["s1", "s2"]
    runtime = fleet.runtimes(**data.dependencies, now=NOW, health="failed", q="RUNTIME-a")
    RuntimeFleetPage.model_validate(runtime)
    assert runtime["items"] == [dict(id="runtime-A", runtime_instance_id="runtime-A", source_count=2, affected_source_count=1, health="failed")]
    unassigned = fleet.sources(**data.dependencies, now=NOW, runtime_id="unassigned")
    assert [s["id"] for s in unassigned["items"]] == ["s3"]
    assert fleet.sources(**data.dependencies, now=NOW, q="SOURCE S2")["total"] == 1
    assert fleet.sources(**data.dependencies, now=NOW, offset=20)["items"] == []
    groups = fleet.runtimes(**data.dependencies, now=NOW, segment="storage")
    assert groups["items"][0]["id"] == "unassigned"
    healthy_group = next(r for r in groups["items"] if r["id"] == "runtime-A")
    assert healthy_group["source_count"] == 2 and healthy_group["affected_source_count"] == 0
    healthy_filter = fleet.runtimes(**data.dependencies, now=NOW, segment="storage", health="healthy")
    assert healthy_filter["items"][0]["affected_source_count"] == 2


def test_priority_orders_copying_by_size_independently_of_retained_publication(data):
    data.add_source("s1", "runtime")
    data.add(mirror("small"), size=10)
    data.add(mirror("large", published=True, status="rebuilding"), size=1000)
    data.add(mirror("missing"), size=None)
    result = fleet.inventory(**data.dependencies, now=NOW)
    assert [item["id"] for item in result["items"]] == ["large", "small", "missing"]


def test_retained_resume_is_copying_but_does_not_queue_a_snapshot(data):
    data.add_source("s1", "runtime")
    data.add(mirror("first"))
    data.add(mirror("resume", published=True, status="unknown"))
    value = mirror("replacement", published=True, status="unknown")
    op = operation(value)
    op["reopen_baseline"] = {"previous_generation_id": "g-replacement"}
    data.add(value, op=op)
    result = fleet.overview(**data.dependencies, now=NOW)
    assert result["states"]["copying"]["count"] == 3
    assert result["snapshot"]["queued"] == 2


def test_sql_inventory_count_does_not_materialize_fleet_and_is_constant_query_count(data):
    if not data.engine:
        pytest.skip("SQL query bound")
    data.add_source("s1", "runtime")
    for i in range(30):
        data.add(mirror("m-%02d" % i))
    statements = []
    def record(_, __, statement, ___, ____, _____):
        statements.append(statement)
    event.listen(data.engine, "before_cursor_execute", record)
    try:
        with data.storage.transaction() as session:
            rows, total, _ = data.storage.fleet(data.telemetry, source_store=data.source_store, catalog_store=data.catalog_store, now=NOW).inventory_page(session, limit=12, offset=12)
        assert total == 30 and len(rows) == 12
        assert len(statements) == 3
        assert "LIMIT" in statements[-1]
    finally:
        event.remove(data.engine, "before_cursor_execute", record)


def test_1024_source_picker_pages_and_attention_totals_reconcile(data):
    if data.engine:
        pytest.skip("The SQL count and page predicates are covered separately")
    for index in range(1024):
        sid = "s%04d" % index
        data.add_source(sid, "runtime-%02d" % (index % 16))
        data.add(mirror("mirror-%04d" % index, source=sid, blocker="continuity" if index % 37 == 0 else None))
    overview = fleet.overview(**data.dependencies, now=NOW, rank="attention")
    assert overview["source_count"] == 1024
    assert len(overview["ranking"]) == 8 and overview["ranking_total"] == 1024
    attention = fleet.inventory(**data.dependencies, now=NOW, grouped_state="attention", offset=12, limit=12, sort="priority")
    assert attention["total"] == overview["attention_count"] == 28
    assert len(attention["items"]) == 12
    assert fleet.sources(**data.dependencies, now=NOW, limit=12, offset=1020)["total"] == 1024
    assert len(fleet.sources(**data.dependencies, now=NOW, limit=12, offset=1020)["items"]) == 4


def test_fleet_diagnostics_batches_observation_reads(data, monkeypatch):
    if data.engine:
        pytest.skip("Diagnostic adapter call bound is independent of SQL fleet projection")
    bindings, mirrors = {}, []
    for index in range(1024):
        sid = "s%04d" % index
        bindings[sid] = dict(runtime_instance_id="runtime", source_id=sid)
        mirrors.append(mirror("m" + sid, source=sid))
    calls = []
    original = data.telemetry.all
    monkeypatch.setattr(data.telemetry, "all", lambda kind: (calls.append(kind), original(kind))[1])
    monkeypatch.setattr(data.telemetry, "read", lambda *_: pytest.fail("Fleet diagnostics must batch telemetry"))
    response = diagnostics.read_diagnostics(store=data.telemetry, read_scope=lambda: (mirrors, bindings), now=NOW)
    assert response["source_count"] == 1024 and len(response["sources"]) == 8
    assert len(calls) == 5


def test_fleet_routes_validate_filters_and_authorize_operations_reader(data):
    if data.engine:
        pytest.skip("The HTTP adapter uses the memory fixture; SQL projections have parity tests")
    import asyncio
    import httpx
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from backend.core.errors import AppError
    from backend.admin.deps import get_current_user
    from backend.admin.role_store import get_role_store
    from backend.admin.roles import SUPER_ADMIN_KEY
    from backend.metadata.mirrors.router import router

    data.add_source("s1", "runtime")
    data.add(mirror("attention-1", blocker="schema"))
    app = FastAPI()
    async def domain_error(_, error):
        return JSONResponse({"code": error.code}, status_code=error.http_status)
    app.add_exception_handler(AppError, domain_error)
    app.state.mirror_diagnostics = data.telemetry
    app.state.mirror_diagnostic_scope = lambda: ([*data.storage.mirrors.values()], {})
    app.state.mirror_fleet_reads = {name: partial(getattr(fleet, name), **data.dependencies)
                                  for name in ("overview", "inventory", "sources", "runtimes")}
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="reader", role_id="role")
    app.dependency_overrides[get_role_store] = lambda: SimpleNamespace(get_by_id=lambda _: SimpleNamespace(key=SUPER_ADMIN_KEY))

    async def run():
        async def tick():
            while True:
                await asyncio.sleep(.01)
        ticker = asyncio.create_task(tick())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fleet.test", timeout=5) as client:
            overview = await asyncio.wait_for(client.get("/mirror-fleet"), 5)
            assert overview.status_code == 200
            assert overview.json()["attention_count"] == 1
            result = await client.get("/mirrors", params=dict(grouped_state="attention", cause="schema", sort="priority", limit=12))
            assert result.status_code == 200 and result.json()["total"] == 1
            assert result.json()["items"][0]["attention_cause"] == "schema"
            assert (await client.get("/mirror-fleet/sources")).json()["total"] == 1
            assert (await client.get("/mirror-fleet/runtimes")).json()["items"][0]["id"] == "runtime"
            assert (await client.get("/mirror-throughput")).status_code == 200
            assert (await client.get("/mirror-throughput?hours=24")).status_code == 200
            assert (await client.get("/mirrors?grouped_state=invalid")).status_code == 422
            assert (await client.get("/mirror-fleet/sources?limit=101")).status_code == 422
            app.dependency_overrides[get_role_store] = lambda: SimpleNamespace(get_by_id=lambda _: SimpleNamespace(key="custom", permissions=[]))
            for endpoint in ("/mirror-fleet", "/mirror-fleet/sources", "/mirror-fleet/runtimes", "/mirrors", "/mirror-throughput"):
                assert (await client.get(endpoint)).status_code == 403
        ticker.cancel()
    asyncio.run(run())
