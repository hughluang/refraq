"""Recovery route contracts against an isolated PostgreSQL Management database."""

from hashlib import sha256
import json
from types import SimpleNamespace

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
from backend.metadata.mirrors.service import MirrorError
from backend.tests.test_capture_preparation import management_engine as management_engine
from backend.tests.test_mirror_generation_allocation import target_dsn as target_dsn
from backend.tests.test_mirror_recovery import Runtime, Target


@pytest.mark.integration
@pytest.mark.parametrize("replay", ["fresh", "current_identity", "prior_identity"])
def test_recovery_admission_requires_replacement_to_own_epoch(management_engine, monkeypatch, replay):
    """Replay cases seed identities persisted by earlier admission of a stale replacement."""
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
