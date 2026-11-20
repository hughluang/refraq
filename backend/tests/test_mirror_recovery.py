"""Offline recovery contract tests; no capture process or external database."""

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker

from backend.metadata.models import SourceCaptureBindingRow, SourceRow
from backend.metadata.mirrors.history import History
from backend.metadata.mirrors.history_models import HistoryGateRow, HistoryInvalidationRow
from backend.metadata.mirrors.models import MirrorRow
from backend.metadata.mirrors import router
from backend.metadata.mirrors.recovery import Recovery, RuntimeDispatchAdapter, bind_recovery, schema_resume_allowed, state_only_graph
from backend.metadata.mirrors.recovery_schemas import RecoveryRequest
from backend.metadata.mirrors.recovery_store import RecoveryRow
from backend.metadata.mirrors.service import CommittedOpenPublication, MirrorError
from backend.metadata.mirrors.types import Authority


@compiles(JSONB, "sqlite")
def sqlite_json(element, compiler, **kw):
    return "JSON"


class Runtime:
    def __init__(self):
        self.validity = "unknown"
        self.calls = []
        self.epoch = "epoch"
        self.fail = False
        self.affected = None
        self.window = None

    def inspect(self, *, session, mirror, now):
        return dict(validity=self.validity, source_id=mirror.source_id,
                    mirror_id=mirror.id, history_epoch=self.epoch, table_identity=mirror.table_identity,
                    observed_at=now, valid_until=now.replace(year=now.year + 1),
                    ownership=True, readiness=True, resources=True,
                    schema=dict(change="unchanged", fingerprint_verified=True),
                    affected_mirror_ids=self.affected or [mirror.id])

    def submit(self, **command):
        self.calls.append(command)
        if self.fail:
            raise MirrorError("MIRROR_READ_UNAVAILABLE", 503)
        return dict(operation_id=command["operation_id"], state="accepted",
                    capture_generation=command["capture_generation"], generation_id=command["generation_id"])


class Target:
    def capture_bound(self, *, mirror_id):
        return dict(source_id="source", history_epoch="epoch",
                    lower_bound=dict(mirror_id=mirror_id, history_epoch="epoch", commit_seq=0, entry_seq=0))

    def invalidate(self, **kwargs):
        return True


@pytest.fixture
def recovery():
    engine = create_engine("sqlite://")
    for table in (SourceRow.__table__, SourceCaptureBindingRow.__table__, MirrorRow.__table__, HistoryGateRow.__table__,
                  HistoryInvalidationRow.__table__, RecoveryRow.__table__):
        table.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 11, 18, 4, tzinfo=timezone.utc)
    with factory.begin() as session:
        session.add(SourceRow(id="source", key="source", locator_key="source", name="Source", kind="database", created_at=now, updated_at=now))
        for mid in ("a", "b"):
            session.add(MirrorRow(id=mid, source_id="source", table_identity=mid, enabled=True,
                                  state=dict(capture_generation="old", published_generation_id="complete")))
            session.add(HistoryGateRow(mirror_id=mid, history_epoch="epoch", lower_commit_seq=0,
                                       lower_entry_seq=0, status="available"))
    runtime = Runtime()
    audits = []
    service = Recovery(session_factory=factory, history=History(session_factory=factory, target=Target()),
                       runtime=RuntimeDispatchAdapter(runtime), clock=lambda: now,
                       retry_delays=(10, 20), audit=lambda **kw: audits.append(kw))
    return service, factory, runtime, audits


def request(service, mid="a", **kwargs):
    return service.request_recovery(mid, action="retry", expected_history_epoch="epoch", actor_user_id="user", **kwargs)


def test_unknown_never_becomes_a_gap_and_request_is_durable(recovery):
    service, factory, runtime, audits = recovery
    first = request(service)
    assert request(service) == first
    assert len(audits) == 1
    service.dispatch(operation_id=first["operation_id"])
    assert service.get_operation(first["operation_id"])["state"] == "unknown"
    with factory() as session:
        assert session.get(HistoryGateRow, "a").history_epoch == "epoch"
        assert session.get(MirrorRow, "a").state["published_generation_id"] == "complete"
    assert runtime.calls == []


def test_loss_commits_all_gates_before_replacement_and_keeps_old_pointer(recovery):
    service, factory, runtime, audits = recovery
    runtime.validity = "lost"
    runtime.affected = ["b", "a"]
    op = request(service)["operation_id"]
    assert service.dispatch(operation_id=op) == "invalidated"
    assert runtime.calls == []
    with factory() as session:
        receipt = session.get(HistoryInvalidationRow, op)
        assert [item["mirror_id"] for item in receipt.transitions] == ["a", "b"]
        assert session.get(HistoryGateRow, "b").status == "invalidating"
        runtime.epoch = session.get(HistoryGateRow, "a").history_epoch
    assert service.dispatch(operation_id=op) == "dispatched"
    command = runtime.calls[0]
    assert command["kind"] == "replacement" and command["empty"] is True
    assert command["origin"] == "recovery"
    assert command["capture_generation"] != "old"
    service.dispatch(operation_id=op)
    assert len(runtime.calls) == 1
    with factory() as session:
        assert session.get(MirrorRow, "a").state["published_generation_id"] == "complete"


def test_retained_resume_preserves_lineage_and_never_invalidates(recovery):
    service, factory, runtime, audits = recovery
    runtime.validity = "retained"
    op = request(service)["operation_id"]
    assert service.dispatch(operation_id=op) == "dispatched"
    assert runtime.calls[0]["kind"] == "resume"
    assert runtime.calls[0]["capture_generation"] == "old"
    with factory() as session:
        assert session.get(HistoryInvalidationRow, op) is None


def test_actual_window_is_rechecked_and_single_source_dispatch_is_serial(recovery, monkeypatch):
    service, factory, runtime, audits = recovery
    monkeypatch.setattr("backend.metadata.capture.configuration.current_schedule_timezone", lambda: "Asia/Shanghai")
    runtime.validity = "lost"
    with factory.begin() as session:
        session.get(SourceRow, "source").snapshot_window = {"start": "01:00", "end": "02:00"}
    op = request(service)["operation_id"]
    service.dispatch(operation_id=op)
    runtime.epoch = service.get_operation(op)["replacement_epoch"]
    assert service.dispatch(operation_id=op) == "invalidated"
    assert runtime.calls == []
    with factory.begin() as session:
        session.get(SourceRow, "source").snapshot_window = {"start": "11:00", "end": "13:00"}
    assert service.dispatch(operation_id=op) == "dispatched"
    runtime.epoch = "epoch"
    second = request(service, "b")["operation_id"]
    service.dispatch(operation_id=second)
    runtime.epoch = service.get_operation(second)["replacement_epoch"]
    assert service.dispatch(operation_id=second) == "invalidated"
    assert len(runtime.calls) == 1


def test_absent_adapter_and_transient_failures_have_durable_bounded_backoff(recovery):
    service, factory, runtime, audits = recovery
    service.runtime = RuntimeDispatchAdapter()
    op = request(service)["operation_id"]
    service.dispatch(operation_id=op)
    first = service.get_operation(op)
    assert first["attempts"] == 1 and first["next_attempt_at"] is not None
    service.dispatch(operation_id=op)
    assert service.get_operation(op)["attempts"] == 1
    for _ in range(2):
        service.clock = lambda: datetime(2027, 1, 1, tzinfo=timezone.utc)
        with factory.begin() as session:
            row = session.get(RecoveryRow, op)
            row.journal = dict(row.journal, next_attempt_at=None)
        service.dispatch(operation_id=op)
    assert service.get_operation(op)["state"] == "blocked"


@pytest.mark.parametrize("action", ["manual", "postpone", "run_now"])
def test_modes_require_reason_and_actor_and_epoch_are_audited(recovery, action):
    service, factory, runtime, audits = recovery
    with pytest.raises(MirrorError):
        service.request_recovery("a", action=action, expected_history_epoch="epoch", actor_user_id="user")
    result = service.request_recovery("a", action=action, expected_history_epoch="epoch", actor_user_id="user", reason="Approved intervention")
    assert audits[0]["detail"]["actor_user_id"] == "user"
    assert audits[0]["detail"]["expected_history_epoch"] == "epoch"
    assert audits[0]["detail"]["reason"] == "Approved intervention"
    if action != "run_now":
        assert service.dispatch(operation_id=result["operation_id"]) == action
        assert runtime.calls == []


def test_publication_uses_existing_guarded_path_and_only_then_releases_busy(recovery):
    service, factory, runtime, audits = recovery
    runtime.validity = "lost"
    op = request(service)["operation_id"]
    service.dispatch(operation_id=op)
    journal = service.get_operation(op)
    runtime.epoch = journal["replacement_epoch"]
    override = dict(action="run_now", expected_history_epoch=runtime.epoch, actor_user_id="user", reason="Approved override")
    accepted = service.request_recovery("a", **override)
    assert accepted["operation_id"] == op
    service.dispatch(operation_id=op)
    lineage = journal["capture_generation"]
    authority = Authority("source", "binding", 1, "runtime", 1, 1, lineage)
    completion = dict(operation_id=op, authority=authority, certificate=dict(
        operation_id=op, generation_id=journal["generation_id"], table_identity="a", capture_generation=lineage,
    ))
    with pytest.raises(MirrorError):
        service.publish_replacement(**completion)

    class Publication:
        certificate = None

        def publish_generation(self, **kw):
            assert kw["operation_id"] == op
            assert kw["generation_id"] == journal["generation_id"]
            self.certificate = kw["certificate"]
            return kw["generation_id"]

        @contextmanager
        def observe_committed(self, *, mirror_id, expected, **kwargs):
            if self.certificate is None:
                yield None
            else:
                position = dict(mirror_id=mirror_id, history_epoch=expected.history_epoch, commit_seq=0, entry_seq=0)
                bound = dict(source_id="source", history_epoch=expected.history_epoch,
                             lower_bound=position, upper_bound=position)
                yield CommittedOpenPublication(expected.generation_id, {}, dict(evidence=self.certificate), 0, bound)

    service.publication = Publication()
    assert service.publish_replacement(**completion) == journal["generation_id"]
    assert service.get_operation(op)["state"] == "applied"
    assert service.request_recovery("a", **override) == accepted
    assert len(audits) == 2

    runtime.epoch = "epoch"
    runtime.affected = ["a", "b"]
    loss = request(service, "b")["operation_id"]
    assert service.dispatch(operation_id=loss) == "invalidated"
    with factory() as session:
        current_epoch = session.get(HistoryGateRow, "a").history_epoch
    with pytest.raises(MirrorError, match="MIRROR_CONTROL_CONFLICT"):
        service.request_recovery("a", **override)
    assert service.publish_replacement(**completion) == journal["generation_id"]
    new_request = service.request_recovery("a", **(override | {"expected_history_epoch": current_epoch}))
    assert new_request["operation_id"] != op


@pytest.mark.parametrize("change", ["unknown", "rename", "drop", "narrow", "truncate", "key"])
def test_unsafe_schema_is_blocked(change):
    assert schema_resume_allowed(dict(change=change, fingerprint_verified=True)) is False


def test_closed_graph_classifier_rejects_mixed_and_unknown_nodes():
    graph = dict(nodes=[dict(id="read", type="read.mirror"), dict(id="write", type="write.entity")],
                 edges=[dict(source="read", target="write")])
    assert state_only_graph(graph, qualify_node=lambda node: True) is True
    assert state_only_graph(graph, qualify_node=lambda node: None) is False
    graph["nodes"].append(dict(id="effect", type="action.http"))
    assert state_only_graph(graph, qualify_node=lambda node: True) is False


def test_router_calls_recovery_service_and_accepts_authoritative_epoch(recovery, monkeypatch):
    service, factory, runtime, audits = recovery
    bind_recovery(service)
    monkeypatch.setattr(router, "get_actor_token_id", lambda request: None)
    try:
        result = router.recovery_request("a", RecoveryRequest(action="retry", expected_history_epoch="epoch"),
                                         SimpleNamespace(), SimpleNamespace(id="user"))
        assert service.get_operation(result["operation_id"])["state"] == "pending"
    finally:
        bind_recovery(None)


def test_run_now_reuses_invalidated_operation_and_bypasses_only_window(recovery, monkeypatch):
    service, factory, runtime, audits = recovery
    runtime.validity = "lost"
    op = request(service)["operation_id"]
    service.dispatch(operation_id=op)
    epoch = service.get_operation(op)["replacement_epoch"]
    with factory.begin() as session:
        session.get(SourceRow, "source").snapshot_window = {"start": "01:00", "end": "02:00"}
    runtime.epoch = epoch
    postponed = service.request_recovery("a", action="postpone", expected_history_epoch=epoch,
                                          actor_user_id="user", reason="Wait for operator")
    assert postponed["operation_id"] == op
    assert service.dispatch(operation_id=op) == "postpone"
    override = service.request_recovery("a", action="run_now", expected_history_epoch=epoch,
                                         actor_user_id="user", reason="Approved window override")
    assert override["operation_id"] == op
    assert service.dispatch(operation_id=op) == "dispatched"
    assert len(runtime.calls) == 1


def test_lost_submit_response_retries_same_generation_and_operation(recovery):
    service, factory, runtime, audits = recovery
    runtime.validity = "lost"
    op = request(service)["operation_id"]
    service.dispatch(operation_id=op)
    journal = service.get_operation(op)
    runtime.epoch = journal["replacement_epoch"]
    runtime.fail = True
    assert service.dispatch(operation_id=op) == "invalidated"
    assert service.get_operation(op)["submission_uncertain"] is True
    runtime.fail = False
    with factory.begin() as session:
        row = session.get(RecoveryRow, op)
        row.journal = dict(row.journal, next_attempt_at=None)
    assert service.dispatch(operation_id=op) == "dispatched"
    assert runtime.calls[0] == runtime.calls[1]


@pytest.mark.parametrize("action", ["manual", "postpone", "run_now", "retry"])
@pytest.mark.parametrize("fail_submit", [True, False], ids=["uncertain", "dispatched"])
def test_submitted_replacement_cannot_be_rewritten(recovery, action, fail_submit):
    service, factory, runtime, audits = recovery
    runtime.validity = "lost"
    op = request(service)["operation_id"]
    service.dispatch(operation_id=op)
    runtime.epoch = service.get_operation(op)["replacement_epoch"]
    override = dict(action="run_now", expected_history_epoch=runtime.epoch, actor_user_id="user", reason="Approved override")
    accepted = service.request_recovery("a", **override)
    runtime.fail = fail_submit
    assert service.dispatch(operation_id=op) == ("invalidated" if fail_submit else "dispatched")
    before = service.get_operation(op)
    assert before["submission_uncertain"] is True
    assert service.request_recovery("a", **override) == accepted
    with pytest.raises(MirrorError, match="MIRROR_CONTROL_CONFLICT"):
        service.request_recovery("a", action=action, expected_history_epoch=runtime.epoch,
                                 actor_user_id="user", reason="Operator decision")
    assert service.get_operation(op) == before
    assert len(audits) == 2
    assert len(runtime.calls) == 1


def test_retained_uncertain_submission_is_source_busy_and_cannot_be_superseded(recovery):
    service, factory, runtime, audits = recovery
    runtime.validity = "retained"
    runtime.fail = True
    op = request(service)["operation_id"]
    service.dispatch(operation_id=op)
    assert service.get_operation(op)["submission_uncertain"] is True
    with pytest.raises(MirrorError, match="MIRROR_CONTROL_CONFLICT"):
        service.request_recovery("a", action="manual", expected_history_epoch="epoch",
                                 actor_user_id="user", reason="Operator decision")
    runtime.fail = False
    second = request(service, "b")["operation_id"]
    assert service.dispatch(operation_id=second) == "pending"
    assert service.get_operation(second)["fault_code"] == "MIRROR_IN_USE"
    assert len(runtime.calls) == 1


@pytest.mark.parametrize("gate", ["schema", "ownership", "readiness", "resources"])
def test_proven_loss_closes_history_even_when_replacement_safety_blocks(recovery, gate):
    service, factory, runtime, audits = recovery
    inspect = runtime.inspect
    runtime.validity = "lost"

    def unsafe(**kwargs):
        evidence = inspect(**kwargs)
        evidence[gate] = dict(change="drop", fingerprint_verified=True) if gate == "schema" else False
        return evidence

    runtime.inspect = unsafe
    op = request(service)["operation_id"]
    assert service.dispatch(operation_id=op) == "invalidated"
    runtime.epoch = service.get_operation(op)["replacement_epoch"]
    service.dispatch(operation_id=op)
    with factory() as session:
        assert session.get(HistoryGateRow, "a").history_epoch != "epoch"
        assert session.get(MirrorRow, "a").state["published_generation_id"] == "complete"
    assert runtime.calls == []


def test_loss_locks_all_affected_gates_in_sorted_order(recovery):
    service, factory, runtime, audits = recovery
    runtime.validity = "lost"
    runtime.affected = ["b", "a"]
    calls = []
    gate = service._gate

    def recording_gate(session, mirror_id):
        calls.append(mirror_id)
        return gate(session, mirror_id)

    service._gate = recording_gate
    op = request(service, "b")["operation_id"]
    calls.clear()
    assert service.dispatch(operation_id=op) == "invalidated"
    assert calls[:2] == ["a", "b"]


def test_prior_request_identity_cannot_undo_a_newer_mode(recovery):
    service, factory, runtime, audits = recovery
    runtime.validity = "lost"
    original = request(service)
    op = original["operation_id"]
    service.dispatch(operation_id=op)
    epoch = service.get_operation(op)["replacement_epoch"]
    first = dict(action="postpone", expected_history_epoch=epoch, actor_user_id="user", reason="Wait")
    assert service.request_recovery("a", **first) == original
    service.request_recovery("a", action="run_now", expected_history_epoch=epoch,
                             actor_user_id="user", reason="Approved override")
    assert service.request_recovery("a", **first) == original
    assert service.get_operation(op)["request"]["action"] == "run_now"
    assert len(audits) == 3


def test_current_schedule_timezone_is_resolved_at_dispatch(recovery, monkeypatch):
    service, factory, runtime, audits = recovery
    runtime.validity = "lost"
    zone = ["UTC"]
    monkeypatch.setattr("backend.metadata.capture.configuration.current_schedule_timezone", lambda: zone[0])
    with factory.begin() as session:
        session.get(SourceRow, "source").snapshot_window = {"start": "11:00", "end": "13:00"}
    op = request(service)["operation_id"]
    service.dispatch(operation_id=op)
    runtime.epoch = service.get_operation(op)["replacement_epoch"]
    assert service.dispatch(operation_id=op) == "invalidated"
    zone[0] = "Asia/Shanghai"
    assert service.dispatch(operation_id=op) == "dispatched"


@pytest.mark.parametrize("gate", ["ownership", "readiness", "resources"])
def test_run_now_does_not_override_safety(recovery, gate):
    service, factory, runtime, audits = recovery
    runtime.validity = "lost"
    op = request(service)["operation_id"]
    service.dispatch(operation_id=op)
    epoch = service.get_operation(op)["replacement_epoch"]
    runtime.epoch = epoch
    service.request_recovery("a", action="run_now", expected_history_epoch=epoch,
                             actor_user_id="user", reason="Window override only")
    inspect = runtime.inspect

    def unsafe(**kwargs):
        return dict(inspect(**kwargs), **{gate: False})

    runtime.inspect = unsafe
    assert service.dispatch(operation_id=op) == "invalidated"
    assert runtime.calls == []


def test_submission_intent_survives_process_failure_before_acknowledgement(recovery):
    service, factory, runtime, audits = recovery
    runtime.validity = "retained"
    op = request(service)["operation_id"]
    submit = runtime.submit

    def crash(**command):
        submit(**command)
        raise RuntimeError("Simulated process exit")

    runtime.submit = crash
    with pytest.raises(RuntimeError, match="Simulated process exit"):
        service.dispatch(operation_id=op)
    persisted = service.get_operation(op)
    assert persisted["state"] == "submitting"
    assert persisted["submission_uncertain"] is True
    assert persisted["submission_command"] == runtime.calls[0]
    with pytest.raises(MirrorError, match="MIRROR_CONTROL_CONFLICT"):
        service.request_recovery("a", action="manual", expected_history_epoch="epoch",
                                 actor_user_id="user", reason="Cannot replace uncertain work")
    runtime.submit = submit
    assert service.dispatch(operation_id=op) == "dispatched"
    assert runtime.calls[0] == runtime.calls[1]


def test_dispatch_rechecks_window_after_committing_submission_intent(recovery, monkeypatch):
    service, factory, runtime, audits = recovery
    runtime.validity = "lost"
    monkeypatch.setattr("backend.metadata.capture.configuration.current_schedule_timezone", lambda: "UTC")
    op = request(service)["operation_id"]
    service.dispatch(operation_id=op)
    runtime.epoch = service.get_operation(op)["replacement_epoch"]
    with factory.begin() as session:
        session.get(SourceRow, "source").snapshot_window = {"start": "04:00", "end": "05:00"}
    prepare = service._prepare_dispatch

    def cross_window(**kwargs):
        state = prepare(**kwargs)
        service.clock = lambda: datetime(2026, 11, 18, 5, tzinfo=timezone.utc)
        return state

    service._prepare_dispatch = cross_window
    assert service.dispatch(operation_id=op) == "invalidated"
    assert service.get_operation(op)["fault_code"] == "MIRROR_SNAPSHOT_WINDOW_CLOSED"
    assert runtime.calls == []


def test_stale_epoch_and_unbound_adapter_fail_closed(recovery):
    service, factory, runtime, audits = recovery
    with pytest.raises(MirrorError, match="MIRROR_CONTROL_CONFLICT"):
        service.request_recovery("a", action="retry", expected_history_epoch="stale", actor_user_id="user")
    assert audits == []
    bind_recovery(None)
    with pytest.raises(MirrorError, match="MIRROR_READ_UNAVAILABLE"):
        router.recovery.request_recovery("a", action="retry", expected_history_epoch="epoch", actor_user_id="user")
