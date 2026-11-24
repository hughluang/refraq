"""Recovery route contracts against an isolated PostgreSQL Management database."""

from datetime import timedelta
from hashlib import sha256
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.admin.audit import persist_audit_event
from backend.admin.deps import get_current_user
from backend.admin.models import AuditEventRow
from backend.admin.role_store import get_role_store
from backend.admin.roles import SUPER_ADMIN_KEY
from backend.core.errors import AppError
from backend.core.time import utc_now
from backend.main import app_error_handler
from backend.metadata.models import SourceRow
from backend.metadata.mirrors import recovery, router
from backend.metadata.mirrors.history import History
from backend.metadata.mirrors.history_models import HistoryGateRow, HistoryInvalidationRow
from backend.metadata.mirrors.models import MirrorRow
from backend.metadata.mirrors.recovery_store import RecoveryRow
from backend.metadata.mirrors.errors import MirrorError
from backend.tests.test_capture_preparation import management_engine as management_engine
from backend.tests.test_mirror_recovery import Runtime, Target


@pytest.fixture(scope="module")
def target_dsn():
    dsn = os.getenv("REFRAQ_MIRROR_ALLOCATION_TEST_DSN")
    if not dsn:
        pytest.skip("Set REFRAQ_MIRROR_ALLOCATION_TEST_DSN to a disposable PostgreSQL server")
    return dsn


@pytest.fixture
def recovery_store(management_engine):
    for model in (SourceRow, MirrorRow, HistoryGateRow, HistoryInvalidationRow, RecoveryRow, AuditEventRow):
        model.__table__.create(management_engine)
    factory = sessionmaker(management_engine)
    now = utc_now()
    with factory.begin() as session:
        session.add(SourceRow(id="source", key="source", locator_key="source", name="Source", kind="database",
                              created_at=now, updated_at=now))
        session.flush()
        for mirror_id in ("a", "b"):
            session.add(MirrorRow(id=mirror_id, source_id="source", table_identity=mirror_id, enabled=True, state={}))
        session.flush()
        for mirror_id in ("a", "b"):
            session.add(HistoryGateRow(mirror_id=mirror_id, history_epoch="epoch", lower_commit_seq=0,
                                       lower_entry_seq=0, status="available"))
    return factory


@pytest.fixture
def recovery_scheduler(recovery_store):
    runtime = Runtime()
    runtime.validity = "lost"
    runtime.affected = ["b", "a"]
    target = Target()
    target.invalidate = Mock(return_value=True)
    history = History(session_factory=recovery_store, target=target)
    clock = Mock(return_value=utc_now())
    service = recovery.Recovery(session_factory=recovery_store, history=history,
                                runtime=recovery.RuntimeDispatchAdapter(runtime), clock=clock,
                                retry_delays=(10,), jitter=lambda lower, upper: upper)
    return service, runtime, target.invalidate, clock


@pytest.mark.integration
@pytest.mark.parametrize("replacement_control", ["manual", "postpone", "observation_unavailable"])
def test_committed_invalidation_precedes_replacement_controls(recovery_store, recovery_scheduler, replacement_control):
    factory = recovery_store
    service, runtime, invalidate_target, _ = recovery_scheduler
    operation_id = service.request_recovery("a", action="retry", expected_history_epoch="epoch",
                                            actor_user_id="user")["operation_id"]
    assert service.dispatch(operation_id=operation_id) == "invalidated"
    invalidate_target.assert_not_called()
    with factory() as session:
        receipt = session.get(HistoryInvalidationRow, operation_id)
        assert receipt.status == "pending"
        transitions = receipt.transitions
        assert [transition["mirror_id"] for transition in transitions] == ["a", "b"]
        assert all(session.get(HistoryGateRow, mid).status == "invalidating" for mid in ("a", "b"))
    runtime.epoch = service.get_operation(operation_id)["replacement_epoch"]

    if replacement_control == "observation_unavailable":
        runtime.inspect = Mock(side_effect=MirrorError("MIRROR_READ_UNAVAILABLE", 503))
        expected = "invalidated"
    else:
        request = service.request_recovery("a", action=replacement_control, expected_history_epoch=runtime.epoch,
                                           actor_user_id="user", reason="Hold replacement")
        assert request["operation_id"] == operation_id
        expected = replacement_control
    assert service.dispatch(operation_id=operation_id) == expected

    with factory() as session:
        receipt = session.get(HistoryInvalidationRow, operation_id)
        assert receipt.status == "applied"
        assert receipt.transitions == transitions
        for transition in transitions:
            gate = session.get(HistoryGateRow, transition["mirror_id"])
            assert (gate.status, gate.history_epoch) == ("available", transition["history_epoch"])
    assert runtime.calls == []
    [call] = invalidate_target.call_args_list
    assert call.kwargs["operation_id"] == operation_id
    assert call.kwargs["transitions"] == transitions


@pytest.mark.integration
@pytest.mark.parametrize("exhaust_budget", [False, True], ids=["eligible_retry", "audited_rearm"])
def test_target_acknowledgement_retries_the_exact_invalidation(recovery_store, recovery_scheduler, exhaust_budget):
    service, runtime, invalidate_target, clock = recovery_scheduler
    hold = dict(action="manual", expected_history_epoch="epoch", actor_user_id="user", reason="Hold replacement")
    unverified = service.request_recovery("a", **hold)["operation_id"]
    assert service.dispatch(operation_id=unverified) == "manual"
    invalidate_target.assert_not_called()
    with recovery_store() as session:
        assert session.get(HistoryInvalidationRow, unverified) is None
        assert session.get(HistoryGateRow, "a").history_epoch == "epoch"

    operation_id = service.request_recovery("a", action="retry", expected_history_epoch="epoch",
                                            actor_user_id="user")["operation_id"]
    assert service.dispatch(operation_id=operation_id) == "invalidated"
    committed = service.get_operation(operation_id)
    hold["expected_history_epoch"] = runtime.epoch = committed["replacement_epoch"]
    if exhaust_budget:
        assert service.request_recovery("a", **hold)["operation_id"] == operation_id
    runtime.inspect = Mock(wraps=runtime.inspect)
    invalidate_target.return_value = False

    def assert_still_closed():
        with recovery_store() as session:
            assert session.get(HistoryInvalidationRow, operation_id).status == "pending"
            assert all(session.get(HistoryGateRow, mid).status == "invalidating" for mid in ("a", "b"))
        assert runtime.calls == []
        runtime.inspect.assert_not_called()

    assert service.dispatch(operation_id=operation_id) == "invalidated"
    assert service.get_operation(operation_id)["fault_code"] == "MIRROR_READ_UNAVAILABLE"
    assert_still_closed()
    assert service.dispatch(operation_id=operation_id) == "invalidated"
    assert invalidate_target.call_count == 1
    clock.return_value += timedelta(seconds=10)

    if exhaust_budget:
        assert service.dispatch(operation_id=operation_id) == "blocked"
        assert_still_closed()
        invalidate_target.return_value = True
        clock.return_value += timedelta(seconds=10)
        assert service.request_recovery("a", **hold)["operation_id"] == operation_id
        assert service.dispatch(operation_id=operation_id) == "blocked"
        assert invalidate_target.call_count == 2
        hold["action"] = "postpone"
        assert service.request_recovery("a", **hold)["operation_id"] == operation_id

    invalidate_target.return_value = True
    assert service.dispatch(operation_id=operation_id) == ("postpone" if exhaust_budget else "dispatched")
    with recovery_store() as session:
        receipt = session.get(HistoryInvalidationRow, operation_id)
        assert receipt.status == "applied"
        transitions = receipt.transitions
        assert all(session.get(HistoryGateRow, mid).status == "available" for mid in ("a", "b"))
    assert invalidate_target.call_count == (3 if exhaust_budget else 2)
    for call in invalidate_target.call_args_list:
        assert call.kwargs["operation_id"] == operation_id
        assert call.kwargs["transitions"] == transitions

    if exhaust_budget:
        assert runtime.calls == []
        runtime.inspect.assert_not_called()
        assert service.request_recovery("a", **dict(hold, action="run_now"))["operation_id"] == operation_id
        assert service.dispatch(operation_id=operation_id) == "dispatched"
    assert service.dispatch(operation_id=operation_id) == "dispatched"
    [command] = runtime.calls
    for key in ("operation_id", "capture_generation", "generation_id"):
        assert command[key] == committed[key]


@pytest.mark.integration
@pytest.mark.parametrize("replay", ["fresh", "current_identity", "prior_identity"])
def test_recovery_admission_requires_replacement_to_own_epoch(recovery_store, monkeypatch, replay):
    """Replay cases seed identities persisted by earlier admission of a stale replacement."""
    factory = recovery_store

    runtime = Runtime()
    history = History(session_factory=factory, target=Target())
    service = recovery.Recovery(session_factory=factory, history=history,
                                runtime=recovery.RuntimeDispatchAdapter(runtime), retry_delays=(1,))
    monkeypatch.setattr(recovery, "_recovery", service)
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(router.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user", role_id="role")
    app.dependency_overrides[get_role_store] = lambda: SimpleNamespace(
        get_by_id=lambda _: SimpleNamespace(key=SUPER_ADMIN_KEY))

    def persisted():
        with factory() as session:
            journals = {row.operation_id: (row.identity, row.journal) for row in session.scalars(select(RecoveryRow))}
            audits = {row.id: (row.actor_user_id, row.resource_id, row.action, row.result, row.detail)
                      for row in session.scalars(select(AuditEventRow))}
            return journals, audits

    def fail_after_audit_flush(**fields):
        persist_audit_event(**fields)
        raise MirrorError("MIRROR_READ_UNAVAILABLE", 503)

    with TestClient(app) as client:
        def post(mirror_id, *, epoch, action="retry", reason=None):
            return client.post(f"/mirrors/{mirror_id}/recovery-requests",
                               json=dict(action=action, expected_history_epoch=epoch, reason=reason))

        earlier = post("a", epoch="epoch", action="manual", reason="Wait for operator")
        assert earlier.status_code == 202
        earlier_id = earlier.json()["operation_id"]
        first = post("a", epoch="epoch")
        assert first.status_code == 202
        operation_id = first.json()["operation_id"]
        assert operation_id != earlier_id
        assert service.get_operation(earlier_id)["state"] == "superseded"
        runtime.validity = "lost"
        assert service.dispatch(operation_id=operation_id) == "invalidated"
        history.consume_invalidation(operation_id=operation_id)
        original = service.get_operation(operation_id)
        epoch = original["replacement_epoch"]
        postponed = post("a", epoch=epoch, action="postpone", reason="Use next window")
        assert postponed.status_code == 202
        assert postponed.json() == first.json()

        before = persisted()
        with monkeypatch.context() as failure:
            failure.setattr(service, "audit", fail_after_audit_flush)
            assert post("a", epoch=epoch, action="run_now", reason="Approved override").status_code == 503
        assert persisted() == before

        accepted = post("a", epoch=epoch, action="run_now", reason="Approved override")
        assert accepted.status_code == 202
        assert accepted.json() == first.json()
        journals, audits = persisted()
        assert journals[earlier_id] == before[0][earlier_id]
        journal = journals[operation_id][1]
        for key in ("replacement_epoch", "capture_generation", "generation_id"):
            assert journal[key] == original[key]
        assert journal["request"]["action"] == "run_now"
        [audit] = [event for audit_id, event in audits.items() if audit_id not in before[1]]
        assert audit == ("user", "a", "mirror.recovery_request", "success",
                         dict(operation_id=operation_id, source_id="source", **journal["request"]))
        duplicate = post("a", epoch=epoch, action="run_now", reason="Approved override")
        assert duplicate.status_code == 202
        assert duplicate.json() == accepted.json()
        prior = post("a", epoch=epoch, action="postpone", reason="Use next window")
        assert prior.status_code == 202
        assert prior.json() == accepted.json()
        assert persisted() == (journals, audits)
        assert runtime.calls == []

        second = post("b", epoch="epoch")
        assert second.status_code == 202
        second_id = second.json()["operation_id"]
        runtime.affected = ["b", "a"]
        assert service.dispatch(operation_id=second_id) == "invalidated"
        history.consume_invalidation(operation_id=second_id)
        with factory.begin() as session:
            current_epoch = session.get(HistoryGateRow, "a").history_epoch
            assert current_epoch != epoch
            if replay != "fresh":
                row = session.get(RecoveryRow, operation_id)
                reasons = ["New override"] if replay == "current_identity" else ["New override", "Later override"]
                for reason in reasons:
                    legacy_request = dict(journal["request"], expected_history_epoch=current_epoch, reason=reason)
                    identity = sha256(json.dumps(dict(legacy_request, mirror_id="a"), sort_keys=True).encode()).hexdigest()
                    row.journal = dict(row.journal, request=legacy_request,
                                       request_identities=[*row.journal["request_identities"], identity])
                    row.identity = identity

        before = persisted()
        rejected = post("a", epoch=current_epoch, action="run_now", reason="New override")
        assert rejected.status_code == 409, rejected.json()
        assert rejected.json()["code"] == "MIRROR_CONTROL_CONFLICT"
        assert persisted() == before
        assert runtime.calls == []
