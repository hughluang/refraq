"""Offline management seam contracts; no target or source service connections."""

import pytest

from backend.core.errors import AppError
from backend.metadata.mirrors import service
from backend.metadata.mirrors.store import MemoryMirrorStore


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
    with store.transaction() as session:
        result = service.ensure_open_intent(
            session,
            operation_id="op1",
            channel_id="c1",
            channel_version=1,
            object_ids=["o1", "o1"],
        )
    yield store, result[0]["mirror_id"]
    service.bind_management()


def test_shared_open_is_transactional_and_reused(opened):
    store, mid = opened
    with store.transaction() as session:
        second = service.ensure_open_intent(
            session,
            operation_id="op2",
            channel_id="c2",
            channel_version=1,
            object_ids=["o1"],
        )
    assert second == [dict(source_id="s1", object_id="o1", mirror_id=mid)]
    assert len(store.operations) == 1
    assert store.receipts["op1"]["result"][0]["effect"] == "first_open"
    assert store.receipts["op2"]["result"][0]["effect"] == "shared"
    assert service.current_version_mirrors(channel_id="c2", version=1) == {mid}
    assert service.current_version_mirrors(channel_id="c1", version=2) == set()
    assert service.get_mirror(mid)["published_reference_count"] == 2
    with pytest.raises(RuntimeError):
        with store.transaction() as session:
            service.reconcile_references(
                session, channel_id="c1", channel_version=2, object_ids=[]
            )
            raise RuntimeError("caller rollback")
    assert service.get_mirror(mid)["published_reference_count"] == 2
    with store.transaction() as session:
        service.reconcile_references(
            session, channel_id="c1", channel_version=2, object_ids=[]
        )
    assert service.get_mirror(mid)["published_reference_count"] == 1


def test_reopen_receipt_keeps_effect_on_replay(opened):
    store, mid = opened
    service.set_enabled(mid, enabled=False, actor_user_id="operator")
    binding = service.resolve_object_binding("o1")
    assert binding["effect"] == "reopen"
    identity = dict(source_id="s1", object_id="o1", mirror_id=mid)
    args = dict(operation_id="channel:c1:2", channel_id="c1", channel_version=2,
                object_ids=["o1"], confirmed_mirrors_to_open=[identity])
    with store.transaction() as session:
        assert service.ensure_open_intent(session, **args) == [identity]
    assert service.resolve_object_binding("o1")["effect"] == "shared"
    with store.transaction() as session:
        assert service.ensure_open_intent(session, **args) == [identity]
    assert service.publication_effects(channel_id="c1", version=2) == {"o1": "reopen"}


def test_legacy_publication_only_proves_confirmed_requests(opened):
    store, mid = opened
    identity = dict(source_id="s1", object_id="o1", mirror_id=mid)
    shared = dict(source_id="s1", object_id="o2", mirror_id="m2")
    with store.transaction() as session:
        store.save_receipt(session, "channel:c1:1", {"confirmed_mirrors_to_open": [identity]}, [identity, shared])
    assert service.publication_effects(channel_id="c1", version=1) == {"o1": "request"}


def test_invalid_binding_does_not_partially_open():
    store = MemoryMirrorStore()
    service.bind_management(store=store)
    with pytest.raises(AppError) as error:
        with store.transaction() as session:
            service.ensure_open_intent(
                session,
                operation_id="op",
                channel_id="c",
                channel_version=1,
                object_ids=["missing"],
            )
    assert error.value.code == "MIRROR_NOT_FOUND"
    assert not store.mirrors
    service.bind_management()


def test_control_and_deletion_are_fail_closed(opened):
    store, mid = opened
    result = service.set_enabled(mid, enabled=False, actor_user_id="u")
    assert result["mirror"]["status"] == "disable_pending"
    assert result["mirror"]["control"]["stop_ack"] is None
    assert result["mirror"]["published_generation_id"] is None
    assert {op["kind"]: op["state"] for op in result["mirror"]["operations"]} == {
        "open": "superseded",
        "disable": "pending",
    }
    with pytest.raises(AppError, match="MIRROR_REFERENCED"):
        service.delete_mirror(mid, actor_user_id="u")
    with store.transaction() as session:
        service.reconcile_references(
            session, channel_id="c1", channel_version=2, object_ids=[]
        )
    with pytest.raises(AppError, match="MIRROR_READ_UNAVAILABLE"):
        service.delete_mirror(mid, actor_user_id="u")

    class Pinned:
        def close_for_delete(self, **kwargs):
            raise service.MirrorError("MIRROR_IN_USE", 409)

    service.bind_management(store=store, target=Pinned())
    with pytest.raises(AppError, match="MIRROR_IN_USE"):
        service.delete_mirror(mid, actor_user_id="u")
    assert service.get_mirror(mid)["enabled"] is False

    calls = []

    class Closed:
        def close_for_delete(self, **kwargs):
            calls.append(kwargs)

    service.bind_management(store=store, target=Closed())
    service.delete_mirror(mid, actor_user_id="u")
    assert calls == [dict(mirror_id=mid, source_id="s1", control_revision=2)]
    assert service.list_mirrors()["total"] == 0
    from backend.admin.audit_store import get_audit_store

    events, _ = get_audit_store().list_events(limit=100)
    assert any(event.action == "mirror.delete" for event in events)


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


def test_stale_versions_and_changed_binding_reject(opened):
    store, mid = opened
    with store.transaction() as session:
        service.reconcile_references(
            session, channel_id="c1", channel_version=3, object_ids=[]
        )
    with pytest.raises(AppError, match="MIRROR_CONTROL_CONFLICT"):
        with store.transaction() as session:
            service.ensure_open_intent(
                session,
                operation_id="late",
                channel_id="c1",
                channel_version=2,
                object_ids=["o1"],
            )
    store.bindings["o1"]["qualified_table"] = "other.orders"
    with pytest.raises(AppError, match="MIRROR_CONTROL_CONFLICT"):
        with store.transaction() as session:
            service.ensure_open_intent(
                session,
                operation_id="changed",
                channel_id="c2",
                channel_version=1,
                object_ids=["o1"],
            )


def test_sql_caller_transaction_rollback_without_service_connections():
    from contextlib import contextmanager
    from sqlalchemy import create_engine, Column, MetaData, String, Table
    from sqlalchemy.orm import Session
    from backend.metadata.mirrors.models import (
        MirrorRow,
        MirrorReferenceRow,
        MirrorOperationRow,
        MirrorPublicationRow,
        MirrorIntentReceiptRow,
    )
    from backend.metadata.mirrors.store import SqlMirrorStore

    engine = create_engine("sqlite://")
    metadata = MetaData()
    Table("sources", metadata, Column("id", String(64), primary_key=True))
    metadata.create_all(engine)
    tables = [
        MirrorRow.__table__,
        MirrorReferenceRow.__table__,
        MirrorOperationRow.__table__,
        MirrorPublicationRow.__table__,
        MirrorIntentReceiptRow.__table__,
        service.HistoryGateRow.__table__,
    ]
    for table in tables:
        table.create(engine)

    class Store(SqlMirrorStore):
        @contextmanager
        def transaction(self):
            with Session(engine) as session, session.begin():
                yield session

        def binding(self, session, object_id):
            return dict(
                source_id="s1",
                object_id="o1",
                source_key="sales",
                source_name="Sales",
                qualified_table="public.orders",
                table_identity="o1",
            )

    store = Store()
    service.bind_management(store=store)
    try:
        with pytest.raises(RuntimeError):
            with store.transaction() as session:
                service.ensure_open_intent(
                    session,
                    operation_id="rollback",
                    channel_id="c1",
                    channel_version=1,
                    object_ids=["o1"],
                )
                raise RuntimeError("caller rollback")
        assert service.list_mirrors()["total"] == 0
        with store.transaction() as session:
            result = service.ensure_open_intent(
                session,
                operation_id="commit",
                channel_id="c1",
                channel_version=1,
                object_ids=["o1"],
            )
        assert (
            service.get_mirror(result[0]["mirror_id"])["published_reference_count"] == 1
        )
        with store.transaction() as session:
            assert (
                service.ensure_open_intent(
                    session,
                    operation_id="commit",
                    channel_id="c1",
                    channel_version=1,
                    object_ids=["o1"],
                )
                == result
            )
    finally:
        service.bind_management()
        engine.dispose()


def test_http_strict_management_projection(opened, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from backend.admin.deps import get_current_user
    from backend.admin.role_store import get_role_store
    from backend.metadata.mirrors.router import router
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


def test_progress_projects_only_current_correlated_notifications(opened, monkeypatch):
    from backend.metadata.capture.store import get_source_store
    from backend.metadata.mirrors.schemas import Mirror

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

    assert Mirror.model_validate(service.get_mirror(mid)).progress is None
    snapshot["scan"] = dict(offset=1, timestamp=1700000000123)
    progress = Mirror.model_validate(service.get_mirror(mid)).progress
    assert progress.stage == "scan"
    assert progress.observed_at.isoformat() == "2023-11-14T22:13:20.123000+00:00"
    snapshot.update(state="catching_up", completion=dict(offset=2, timestamp=1700000001456))
    assert service.list_mirrors()["items"][0]["progress"]["stage"] == "catching_up"
    snapshot["binding"]["allocation_operation_id"] = "unrelated"
    assert service.get_mirror(mid)["progress"] is None
    snapshot["binding"]["allocation_operation_id"] = op["id"]
    state["owner_epoch"] += 1
    assert service.get_mirror(mid)["progress"] is None


def test_same_intent_keeps_revision_and_real_enable_creates_a_consumable_open(opened):
    store, mid = opened
    original = next(iter(store.operations))
    repeated = service.set_enabled(mid, enabled=True, actor_user_id="u")
    assert repeated["operation_id"] == original
    assert repeated["mirror"]["control"]["control_revision"] == 1

    disabled = service.set_enabled(mid, enabled=False, actor_user_id="u")
    assert service.set_enabled(mid, enabled=False, actor_user_id="u") == disabled
    reopened = service.set_enabled(mid, enabled=True, actor_user_id="u")
    assert service.set_enabled(mid, enabled=True, actor_user_id="u") == reopened
    assert store.operations[original]["state"] == "superseded"
    assert store.operations[disabled["operation_id"]]["state"] == "superseded"
    pending = store.operations[reopened["operation_id"]]
    assert (pending["kind"], pending["state"], pending["control_revision"]) == ("open", "pending", 3)


def test_history_only_publication_preserves_disabled_intent_and_refcounts(opened):
    store, mid = opened
    service.set_enabled(mid, enabled=False, actor_user_id="u")
    with store.transaction() as session:
        result = service.ensure_open_intent(
            session, operation_id="history", channel_id="c2", channel_version=1,
            object_ids=[], existing_mirror_ids=[mid, mid], confirmed_mirrors_to_open=[])
    assert result == []
    assert service.get_mirror(mid)["enabled"] is False
    assert service.get_mirror(mid)["published_reference_count"] == 2
    assert {op["kind"] for op in store.operations.values()} == {"open", "disable"}
    with pytest.raises(service.MirrorError, match="MIRROR_CONTROL_CONFLICT"):
        with store.transaction() as session:
            service.ensure_open_intent(session, operation_id="history", channel_id="c2", channel_version=1,
                                       object_ids=[], confirmed_mirrors_to_open=[])
