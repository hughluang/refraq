"""Offline management seam contracts; no target or source service connections."""

import pytest

from backend.core.errors import AppError
from backend.metadata.mirrors import service
from backend.metadata.mirrors.store import MemoryMirrorStore
from backend.tests.mirror_inventory import inventory, inventory_dependencies


@pytest.fixture
def opened():
    store = MemoryMirrorStore()
    service.bind_management(store=store)
    store.bindings["o1"] = dict(
        source_id="s1",
        object_id="o1",
        source_key="sales",
        source_name="Sales",
        qualified_table="public.orders",
        table_identity="o1",
    )
    result = service.enable_for_object("o1", actor_user_id="u")
    yield store, result["mirror"]["id"]
    service.bind_management()


def test_never_dispatched_mirror_can_be_deleted_and_reenrolled(opened):
    _, mid = opened
    with pytest.raises(AppError, match="MIRROR_IN_USE"):
        service.delete_mirror(mid, actor_user_id="u")
    stopped = service.set_enabled(mid, enabled=False, actor_user_id="u")
    assert stopped["mirror"]["status"] == "disable_pending"
    assert service.delete_mirror(mid, actor_user_id="u") is None
    assert inventory()["total"] == 0
    new = service.enable_for_object("o1", actor_user_id="u")["mirror"]
    assert new["id"] != mid and new["history_epoch"] is None
    from backend.admin.audit_store import get_audit_store

    events, _ = get_audit_store().list_events(limit=100)
    assert any(event.action == "mirror.delete" and event.resource_id == mid for event in events)


def test_unobserved_allocation_requires_a_stop_before_delete(opened):
    store, mid = opened
    with store.transaction() as session:
        op, = store.ops(session, mid)
        store.save_op(session, dict(op, allocation={"generation_id": "possibly-committed", "observed": False}))
    service.set_enabled(mid, enabled=False, actor_user_id="u")
    with pytest.raises(AppError, match="MIRROR_STOP_UNCONFIRMED"):
        service.delete_mirror(mid, actor_user_id="u")
    assert service.get_mirror(mid)["enabled"] is False


@pytest.mark.parametrize("transition", ["reopen", "retire"])
def test_pre_journal_stop_receipt_survives_authority_change(opened, transition):
    from backend.core.time import utc_now

    store, mid = opened
    stop_id = service.set_enabled(mid, enabled=False, actor_user_id="u")["operation_id"]
    at = utc_now().isoformat()
    source_op = "source-stop"
    with store.transaction() as session:
        mirror = store.get(session, mid)
        mirror.update(status="disabled", published_generation_id="published", history_epoch="epoch")
        revision = mirror["control"]["control_revision"]
        mirror["control"].update(applied_revision=revision, observed_at=at,
                                 stop_ack=dict(operation_id=stop_id, source_operation_id=source_op, observed_at=at))
        store.save(session, mirror)
        operation = next(op for op in store.ops(session, mid) if op["id"] == stop_id)
        store.save_op(session, dict(operation, state="applied", observed_evidence_refs=["unrelated"]))
    assert service.get_mirror_detail(mid)["mirror"]["latest_observation"] is None
    with store.transaction() as session:
        store.save_op(session, dict(operation, state="applied", observed_evidence_refs=[source_op]))
    detail = service.get_mirror_detail(mid)["mirror"]
    assert detail["latest_request"]["outcome_at"] == at
    receipt = detail["latest_observation"]
    assert (receipt["kind"], receipt["at"], receipt["operation_id"], receipt["generation_id"]) == (
        "stop_confirmed", at, stop_id, "published")
    if transition == "reopen":
        service.set_enabled(mid, enabled=True, actor_user_id="u")
    else:
        service.clear_mirror_stop_evidence(None, [{"mirror_id": mid}], source_op)
    events = service.get_mirror_journal(mid)["items"]
    assert [event for event in events if event["kind"] == "stop_confirmed"] == [receipt]
    stop = next(event for event in events if event["id"] == stop_id)
    assert stop["outcome"] == ("stop_confirmed" if transition == "reopen" else "awaiting_stop")


def test_recovery_requires_authoritative_binding(opened, monkeypatch):
    from backend.metadata.mirrors import recovery

    store, mid = opened
    monkeypatch.setattr(recovery, "_recovery", None)
    with pytest.raises(AppError, match="MIRROR_READ_UNAVAILABLE"):
        recovery.request_recovery(
            mid, action="retry", expected_history_epoch="epoch", actor_user_id="u"
        )
    assert service.get_mirror(mid)["history_epoch"] is None
    assert len(store.operations) == 1


def test_http_strict_management_projection(opened, monkeypatch):
    from functools import partial

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from backend.admin.deps import get_current_user
    from backend.admin.role_store import get_role_store
    from backend.metadata.mirrors.router import router
    from backend.metadata.mirrors import fleet
    from backend.admin.roles import SUPER_ADMIN_KEY

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from backend.metadata.models import SourceRow
    from backend.metadata.mirrors.models import MirrorRow
    from backend.metadata.mirrors.history_models import HistoryGateRow
    from backend.metadata.mirrors.recovery_store import RecoveryRow
    from backend.metadata.mirrors.recovery import Recovery
    from backend.metadata.mirrors import recovery
    from backend.main import app_error_handler
    from backend.core.time import utc_now

    store, mid = opened
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    for table in (SourceRow.__table__, MirrorRow.__table__, HistoryGateRow.__table__, RecoveryRow.__table__):
        table.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    now = utc_now()
    with factory.begin() as session:
        session.add(SourceRow(id="s1", key="s1", locator_key="s1", name="Source", kind="database", created_at=now, updated_at=now))
        session.add(MirrorRow(id=mid, source_id="s1", table_identity="o1", enabled=True, state=store.mirrors[mid]))
        session.add(HistoryGateRow(mirror_id=mid, history_epoch="epoch", lower_commit_seq=0, lower_entry_seq=0, status="available"))
    bound = Recovery(session_factory=factory, history=None, retry_delays=(1,), audit=lambda **kwargs: None)
    monkeypatch.setattr(recovery, "_recovery", bound)
    app = FastAPI()
    app.state.mirror_fleet_reads = {"inventory": partial(fleet.inventory, **inventory_dependencies())}
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="u", role_id="r"
    )
    app.dependency_overrides[get_role_store] = lambda: SimpleNamespace(
        get_by_id=lambda _: SimpleNamespace(key=SUPER_ADMIN_KEY)
    )
    with TestClient(app) as client:
        response = client.get("/mirrors")
        assert response.status_code == 200
        assert response.json()["items"][0]["progress"] is None
        assert (
            client.patch(
                f"/mirrors/{mid}", json={"enabled": False, "raw_settings": {}}
            ).status_code
            == 422
        )
        response = client.patch(f"/mirrors/{mid}", json={"enabled": False})
        assert response.status_code == 200
        assert response.json()["mirror"]["status"] == "disable_pending"
        assert client.get("/mirrors", params={"q": "%"}).json()["total"] == 0
        assert client.get("/mirrors", params={"limit": 501}).status_code == 422
        response = client.post(f"/mirrors/{mid}/recovery-requests", json={"action": "retry", "expected_history_epoch": "epoch"})
        assert response.status_code == 202
        assert response.json()["state"] == "pending"
        assert bound.get_operation(response.json()["operation_id"])["state"] == "pending"
        monkeypatch.setattr(recovery, "_recovery", None)
        unavailable = client.post(f"/mirrors/{mid}/recovery-requests", json={"action": "retry", "expected_history_epoch": "epoch"})
        assert unavailable.status_code == 503
        assert unavailable.json()["code"] == "MIRROR_READ_UNAVAILABLE"
        app.dependency_overrides[get_role_store] = lambda: SimpleNamespace(get_by_id=lambda _: SimpleNamespace(key="custom", permissions=[]))
        assert client.get("/mirrors/unknown").status_code == 403
    engine.dispose()


def test_data_key_is_intersection_not_new_role_seed():
    from backend.admin.role_store import get_role_store
    from backend.admin.roles import create_role, OPERATOR_DEFAULT_PERMISSIONS
    from backend.admin.user_store import get_user_store
    from backend.metadata.source_access import create_membership, effective_permissions

    roles = get_role_store()
    role = create_role(roles, key="reader", name="Reader", permissions=["sources:data_read"])
    user = get_user_store().create_user(account="mirror-reader", display_name="Reader", password_hash=None, role_id=role.id)
    assert effective_permissions(user.id, "s1") == frozenset()
    create_membership(subject_type="user", subject_id=user.id, target="s1", level="viewer")
    assert effective_permissions(user.id, "s1") == frozenset({"sources:data_read"})
    role.permissions = []
    roles.save(role)
    assert effective_permissions(user.id, "s1") == frozenset()
    assert "sources:data_read" not in OPERATOR_DEFAULT_PERMISSIONS


def test_authorization_requires_active_user_role_and_membership(monkeypatch):
    from types import SimpleNamespace
    from backend.metadata.mirrors.authorization import authorize_source_data
    from backend.admin.user_store import get_user_store
    from backend.admin.role_store import get_role_store
    from backend.metadata import source_access

    monkeypatch.setattr(
        get_user_store(),
        "get_by_id",
        lambda _: SimpleNamespace(
            id="u", status="active", identity_source="local", role_id="r"
        ),
    )
    monkeypatch.setattr(
        get_role_store(),
        "get_by_id",
        lambda _: SimpleNamespace(key="custom", permissions=[]),
    )
    monkeypatch.setattr(source_access, "effective_level", lambda *_: "viewer")
    monkeypatch.setattr(source_access, "effective_permissions", lambda *_: frozenset())
    with pytest.raises(AppError, match="AUTH_FORBIDDEN"):
        authorize_source_data(execution_user_id="u", source_id="s")
    monkeypatch.setattr(
        source_access,
        "effective_permissions",
        lambda *_: frozenset({"sources:data_read"}),
    )
    monkeypatch.setattr(
        get_role_store(),
        "get_by_id",
        lambda _: SimpleNamespace(key="custom", permissions=["sources:data_read"]),
    )
    authorize_source_data(execution_user_id="u", source_id="s")
    monkeypatch.setattr(
        get_user_store(),
        "get_by_id",
        lambda _: SimpleNamespace(
            status="disabled", identity_source="local", role_id="r"
        ),
    )
    with pytest.raises(AppError, match="AUTH_FORBIDDEN"):
        authorize_source_data(execution_user_id="u", source_id="s")


@pytest.fixture
def snapshotting(opened, monkeypatch):
    from backend.metadata.capture.store import get_source_store

    store, mid = opened
    op = next(iter(store.operations.values()))
    authority = dict(source_id="s1", resource_binding_id="binding", owner_epoch=1,
                     runtime_instance_id="runtime", control_revision=4, credential_revision=2,
                     capture_generation="3")
    binding = dict(authority=authority, object_id="o1", table_identity="o1", qualified_table="public.orders",
                   history_epoch="epoch", schema_fingerprint="schema", partition_identity={"partition": 0})
    op["allocation"] = dict(generation_id="generation", observed=True, mirror_revision=1, binding=binding)
    snapshot = dict(id="signal", receipt=True, state="snapshotting", binding=dict(
        authority=authority, mirror_id=mid, mirror_revision=1, allocation_operation_id=op["id"],
        generation_id="generation", table_identity="o1", qualified_table="public.orders",
        history_epoch="epoch", schema_fingerprint="schema", data_partition={"partition": 0}))
    state = dict(authority, desired="configured", binding_id="binding", applied_revision=4,
                 published_scope=service.read_published_scope(store, "s1"),
                 incremental_snapshots=dict(active="generation", generations={"generation": snapshot}))
    monkeypatch.setitem(get_source_store().capture_bindings, "s1", state)
    return store, mid, state, snapshot


def test_progress_projects_only_current_correlated_notifications(snapshotting):
    from backend.metadata.mirrors.schemas import Mirror

    store, mid, state, snapshot = snapshotting
    op = next(iter(store.operations.values()))

    assert Mirror.model_validate(service.get_mirror(mid)).progress is None
    snapshot["progress_sample"] = dict(offset=0, timestamp=1700000000000)
    progress = Mirror.model_validate(service.get_mirror(mid)).progress
    assert (progress.stage, progress.scanned_bytes, progress.scan_percent, progress.scan_complete) == ("scan", None, None, False)
    snapshot["progress_sample"].update(scanned_bytes=12, scan_total_bytes=48)
    progress = Mirror.model_validate(service.get_mirror(mid)).progress
    assert (progress.scanned_bytes, progress.scan_percent, progress.scan_complete) == (12, 25, False)
    assert progress.bytes_observed_at is None and progress.byte_notification_offset is None
    snapshot["byte_sample"] = dict(scanned_bytes=12, scan_total_bytes=48, offset=0, timestamp=1700000000000)
    snapshot["progress_sample"] = dict(offset=1, timestamp=1700000000100)
    progress = Mirror.model_validate(service.get_mirror(mid)).progress
    assert progress.notification_offset == 1 and progress.byte_notification_offset == 0
    assert progress.bytes_observed_at.isoformat() == "2023-11-14T22:13:20+00:00"
    assert progress.observed_at.isoformat() == "2023-11-14T22:13:20.100000+00:00"
    snapshot["scan"] = dict(offset=1, timestamp=1700000000123)
    progress = Mirror.model_validate(service.get_mirror(mid)).progress
    assert progress.stage == "scan"
    assert progress.observed_at.isoformat() == "2023-11-14T22:13:20.123000+00:00"
    snapshot.update(state="catching_up", completion=dict(offset=2, timestamp=1700000001456))
    catching_up = Mirror.model_validate(service.get_mirror(mid))
    assert catching_up.status == "catching_up" and catching_up.progress.scan_percent == 100
    assert catching_up.progress.scan_complete and catching_up.published_generation_id is None
    assert catching_up.operations[0].state == "pending" and catching_up.history_epoch is None
    assert inventory()["items"][0]["progress"]["stage"] == "catching_up"
    snapshot["binding"]["allocation_operation_id"] = "unrelated"
    assert service.get_mirror(mid)["progress"] is None
    snapshot["binding"]["allocation_operation_id"] = op["id"]
    state["owner_epoch"] += 1
    assert service.get_mirror(mid)["progress"] is None


def test_inventory_filters_the_same_observed_status_as_detail(snapshotting):
    store, mid, _, snapshot = snapshotting
    snapshot.update(state="catching_up", scan=dict(offset=1, timestamp=1700000000123),
                    completion=dict(offset=2, timestamp=1700000001456))
    assert service.get_mirror_detail(mid)["mirror"]["status"] == "catching_up"
    listed, = inventory()["items"]
    assert listed["status"] == "catching_up"
    matching = inventory(status="catching_up", source_id="s1", q="orders", limit=1)
    assert matching["total"] == 1 and matching["items"][0]["id"] == mid
    assert inventory(status="catching_up", offset=1)["total"] == 1
    assert inventory(status="catching_up", offset=1)["items"] == []
    assert inventory(status="waiting")["total"] == 0
    assert inventory(status="catching_up", source_id="hidden")["total"] == 0
    assert store.mirrors[mid]["status"] == "waiting"


@pytest.mark.parametrize("receipt", [False, True])
def test_current_blocked_snapshot_is_observable_and_keeps_its_slot(snapshotting, receipt):
    _, mid, state, snapshot = snapshotting
    snapshot.update(state="blocked", receipt=receipt, fault="snapshot_notification_conflict")
    detail = service.get_mirror_detail(mid)["mirror"]
    assert detail["status"] == "needs_attention" and detail["progress"] is None
    assert {item["key"]: item["result"] for item in detail["readiness"]} == {
        "capture_admission": "pass", "incremental_snapshot_blocked": "fail",
    }
    assert inventory(status="needs_attention")["total"] == 1
    assert state["incremental_snapshots"]["active"] == "generation"
    snapshot["binding"]["allocation_operation_id"] = "other-request"
    assert service.get_mirror_detail(mid)["mirror"]["status"] == "waiting"
    assert inventory(status="needs_attention")["total"] == 0


def test_retained_published_copy_reports_ready_after_open_confirmation(opened):
    store, mid = opened
    mirror = store.mirrors[mid]
    mirror.update(status="unknown", published_generation_id="published")
    next(iter(store.operations.values()))["state"] = "applied"
    assert service.get_mirror_detail(mid)["mirror"]["status"] == "ready"
    assert inventory(status="ready")["total"] == 1
    assert inventory(status="unknown")["total"] == 0


@pytest.mark.parametrize("replacement_first", [False, True])
def test_applied_open_admission_follows_the_replacement_publication(snapshotting, replacement_first):
    store, mid, _, _ = snapshotting
    original, = store.operations.values()
    original.update(state="applied", publication_receipt={"generation_id": "generation"})
    replacement = dict(original, id="replacement", allocation=dict(original["allocation"], generation_id="new"),
                       publication_receipt={"generation_id": "new"})
    operations = (replacement, original) if replacement_first else (original, replacement)
    store.operations = {op["id"]: op for op in operations}
    store.mirrors[mid]["published_generation_id"] = "new"

    detail = service.get_mirror_detail(mid)["mirror"]
    assert detail["profile"]["qualification"] == "qualified"
    assert [(item["key"], item["result"]) for item in detail["readiness"]] == [("capture_admission", "pass")]


def test_filtered_inventory_uses_one_candidate_snapshot_during_enrollment(opened, monkeypatch):
    from backend.metadata.mirrors.fleet_store import FleetStore

    store, mid = opened
    original = store.mirrors.pop(mid)
    store.operations.clear()
    for index in range(1, 102):
        mirror = dict(original, id=f"mirror-{index:03}", qualified_table=f"public.table_{index:03}",
                      status="ready", published_generation_id=f"copy-{index}")
        store.mirrors[mirror["id"]] = mirror
    page = FleetStore.inventory_page

    def enroll_after_read(fleet, session, **query):
        result = page(fleet, session, **query)
        store.mirrors["new"] = dict(original, id="new", qualified_table="public.table_000", status="ready",
                                    published_generation_id="new-copy")
        return result

    monkeypatch.setattr(FleetStore, "inventory_page", enroll_after_read)
    result = inventory(status="ready", limit=500)
    identities = [item["id"] for item in result["items"]]
    assert result["total"] == len(identities) == len(set(identities)) == 101


def test_same_intent_keeps_revision_and_real_enable_creates_a_consumable_open(opened):
    store, mid = opened
    original = next(iter(store.operations))
    repeated = service.set_enabled(mid, enabled=True, actor_user_id="u")
    assert repeated["operation_id"] == original
    assert repeated["mirror"]["control"]["control_revision"] == 1

    disabled = service.set_enabled(mid, enabled=False, actor_user_id="u")
    assert service.set_enabled(mid, enabled=False, actor_user_id="u") == disabled
    reopened = service.enable_for_object("o1", actor_user_id="u")
    assert reopened["mirror"]["id"] == mid
    assert service.enable_for_object("o1", actor_user_id="u") == reopened
    assert store.operations[original]["state"] == "superseded"
    assert store.operations[disabled["operation_id"]]["state"] == "superseded"
    pending = store.operations[reopened["operation_id"]]
    assert (pending["kind"], pending["state"], pending["control_revision"]) == ("open", "pending", 3)



def test_catalog_enable_reuses_operator_request_after_runtime_reallocates(opened):
    from datetime import timedelta

    store, mid = opened
    original, = store.operations.values()
    original["state"] = "superseded"
    replacement = dict(original, id="runtime-open", state="pending",
                       requested_at=(service.utc_now() + timedelta(seconds=1)).isoformat())
    del replacement["operator_intent"]
    with store.transaction() as session:
        store.save_op(session, replacement)

    repeated = service.enable_for_object("o1", actor_user_id="u")
    assert repeated["operation_id"] == original["id"]
    assert repeated["mirror"]["id"] == mid
    assert len(repeated["mirror"]["operations"]) == 2


def test_partial_table_preparation_keeps_sibling_admission_unknown(snapshotting):
    store, mid, state, _ = snapshotting
    store.bindings["items"] = dict(store.bindings["o1"], object_id="items", table_identity="items",
                                   qualified_table="public.items")
    sibling = service.enable_for_object("items", actor_user_id="u")
    state["published_scope"] = service.read_published_scope(store, "s1")
    orders = service.get_mirror(mid)
    items = service.get_mirror(sibling["mirror"]["id"])
    assert orders["profile"]["qualification"] == "qualified"
    assert items["profile"]["qualification"] == "unverified"
    assert all(item["result"] != "pass" for item in items["readiness"])


def test_catching_up_sibling_waits_for_publication_after_slot_release(snapshotting):
    store, mid, state, scan = snapshotting
    store.bindings["items"] = dict(store.bindings["o1"], object_id="items", table_identity="items",
                                   qualified_table="public.items")
    sibling = service.enable_for_object("items", actor_user_id="u")
    state["incremental_snapshots"]["active"] = None
    scan.update(state="catching_up", scan=dict(offset=1, timestamp=1), completion=dict(offset=2, timestamp=2))
    detail = service.get_mirror(sibling["mirror"]["id"])
    assert detail["snapshot_slot_holder"] is None
    assert detail["publication_wait"] == dict(mirror_id=mid, qualified_table="public.orders")
    assert [item["key"] for item in detail["readiness"]] == ["publication_pending"]
    assert service.get_mirror(mid)["publication_wait"] is None


def test_diagnostics_reads_enrolled_registry_without_capture_or_target(opened):
    from functools import partial
    from backend.metadata.mirrors import diagnostics
    from backend.metadata.mirrors.diagnostic_store import DiagnosticStore
    from backend.metadata.sources.store import get_source_store

    mirror_store, mid = opened
    store = DiagnosticStore(memory=True, transaction=None)
    read_scope = partial(service.diagnostic_scope, mirror_store=mirror_store, source_store=get_source_store())
    rows, bindings = read_scope()
    assert rows[0]["id"] == mid and rows[0]["allocated_generation_id"] is None
    view = diagnostics.read_diagnostics(store=store, read_scope=read_scope, source_id="s1")
    assert view["mirror_count"] == 1 and view["link_counts"]["unobserved"] == 4
    detail = diagnostics.mirror_measurements(mid, store=store, read_scope=read_scope, read_detail=service.get_mirror_detail)
    assert detail["sample"] is None and detail["row_sample"] is None
