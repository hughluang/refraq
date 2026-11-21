"""Protected replacement admission through Recovery and Capture Runtime."""

from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
import json
import time
from unittest.mock import Mock

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import psycopg
from psycopg import sql
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.admin.audit import persist_audit_event
from backend.admin.models import AuditEventRow
from backend.core.time import utc_now
from backend.metadata.capture import control
from backend.metadata.capture import delivery_composition as composition
from backend.metadata.capture.delivery import DeliveryLimits, KafkaDelivery
from backend.metadata.capture.runtime import CaptureRuntime
from backend.metadata.capture.runtime_adapters import ReadinessSignals
from backend.metadata.capture.runtime_store import CommandJournal, RuntimeBlocked
from backend.metadata.capture.store import load_binding, load_operation, save_binding
from backend.metadata.capture.test_delivery import FakeConsumer, KEY, Message, SCHEMA, envelope
from backend.metadata.capture.test_published_scope import SOURCE, management as management
from backend.metadata.capture.test_runtime import CHECKS
from backend.metadata.capture.test_start import token, verifier
from backend.metadata.errors import SourceCaptureControlConflict
from backend.metadata.mirrors import bootstrap
from backend.metadata.mirrors import service
from backend.metadata.mirrors.application import Application
from backend.metadata.mirrors.history import History
from backend.metadata.mirrors.history_models import HistoryGateRow, HistoryInvalidationRow
from backend.metadata.mirrors.models import MirrorRow
from backend.metadata.mirrors.recovery import Recovery, RuntimeDispatchAdapter
from backend.metadata.mirrors.recovery_store import RecoveryRow
from backend.metadata.mirrors.types import Authority, PartitionIdentity
from backend.metadata.sources.store import get_source_store
from backend.tests.test_capture_preparation import (
    management_engine as management_engine, native_target as native_target, target_dsn as target_dsn,
)
from backend.tests.test_mirror_recovery import Runtime, Target


def _ref(name):
    return "sha256:" + sha256(name.encode()).hexdigest()


def _prove_snapshot_delivery(monkeypatch, *, dsn, journal, signals, command, key, request_file):
    submission = command["replacement"]["scope"]["submission"]
    mirror_id = submission["mirror_id"]
    generation_id = submission["generation_id"]
    partition = PartitionIdentity("fixture-cluster", "fresh-topic", 0)
    notification = PartitionIdentity("fixture-cluster", "notification-topic", 0)
    profile = Mock(scope=signals.scope, snapshot=dict(signal_table="public.signal", signal_relation_identity="signal",
                                                       notification_topic="cap.notifications",
                                                       notification_partition=asdict(notification)))
    delivery = composition.SourceDelivery(settings_file=None, source_id=SOURCE, journal=journal,
                                          signals=signals, verifier=verifier(key), profile=profile)
    delivery.engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(
        dsn, options="-c role=refraq_mirror_applier",
    ))
    delivery.settings = dict(target=dict(timeout_seconds=1), kafka={}, group_id="replacement")
    delivery.limits, delivery.max_age = DeliveryLimits(), 30
    delivery.manifest_tables = [dict(
        decoder=dict(table_identity="orders", database="db", namespace="cap", schema_name="public",
                     table_name="orders", connector_version="3.7.1.Final", key_schema=KEY, value_schema=SCHEMA),
        partition_identity=asdict(partition), topic="cap.public.orders", schema_fingerprint="fixture-schema",
        native_types=dict(id="integer", body="text"), start_offset=-1,
    )]
    authority = Authority(**composition._target_authority(command))
    events = []
    with psycopg.connect(dsn) as connection:
        fence = connection.execute(
            "SELECT receipt_ref FROM source_mirror_state.fence_receipts WHERE mirror_id = %s AND operation_id = %s",
            (mirror_id, command["operation_id"]),
        ).fetchone()[0]

    def allocate(allocation_command, request, proof, fence_receipt, claimed_id):
        assert (allocation_command, fence_receipt, claimed_id) == (command, fence, generation_id)
        with psycopg.connect(dsn) as connection:
            bootstrap.create_generation(
                connection, mirror_id=mirror_id, generation_id=claimed_id, authority=authority, table_identity="orders",
                history_epoch=submission["history_epoch"], operation_id=command["operation_id"],
                schema_fingerprint="fixture-schema", columns=dict(id="integer", body="text"), key_columns=("id",),
                partition_identity=partition, start_offset=-1, require_prepared_fence=True,
            )

    monkeypatch.setattr(signals, "open_generation_proof", lambda *args: ({}, "fixture-proof", fence))
    monkeypatch.setattr(signals, "allocate_generation", allocate)
    snapshot_record = envelope(op="r", body="replacement baseline", snapshot="incremental")
    snapshot_record["payload"]["source"].update(version="3.7.1.Final", table="orders")

    class SnapshotMessage(Message):
        def topic(self):
            return "cap.public.orders"

    consumer = FakeConsumer([SnapshotMessage(0, snapshot_record)], events)

    def open_client(**options):
        return KafkaDelivery(consumer=consumer, identity=Mock(), application=Application(options["applier_engine"]),
                             binding=options["binding"], decoder=options["decoder"], admission=options["admission"],
                             limits=options["limits"])

    def lease_request(method, path, payload):
        assert method == "POST"
        if path == "/v1/capture/delivery-leases/release":
            assert payload["lease_id"] == "fixture-lease"
            assert ("ack", 1) in events
            events.append(("release",))
            return None
        assert path == "/v1/capture/delivery-leases"
        assert payload["authority"]["capture_generation"] == 2
        assert payload["scope"]["target_metadata"]["status"] == "building"
        events.append(("lease",))
        return dict(signature=token(key, purpose="delivery_lease", authority=payload["authority"],
                                    scope=payload["scope"], operation_id=payload["operation_id"],
                                    facts=dict.fromkeys(composition.FACTS, True), observed_at=time.time(),
                                    lease_id="fixture-lease"))

    monkeypatch.setattr(composition, "open_delivery", open_client)
    monkeypatch.setattr(signals.http, "request", lease_request)
    snapshot = Mock()
    runtime = CaptureRuntime(journal=journal, connect=Mock(), signals=signals, delivery=delivery,
                             prepare_delivery=delivery.prepare, snapshot=snapshot, profile=profile, credentials=Mock())

    def recheck(binding):
        assert binding.generation_id == generation_id
        assert binding.allocation_operation_id == command["operation_id"]
        with control.source_control_transaction(SOURCE) as (session, source):
            assert runtime.recheck_snapshot(binding, session=session, source=source) == "window"
        return Mock(state="snapshotting")

    snapshot.reconcile.side_effect = recheck
    try:
        assert runtime.poll_once(SOURCE, replacement_owner_file=request_file) == "idle"
        snapshot.reconcile.assert_called_once()
        assert events.index(("lease",)) < events.index(("ack", 1)) < events.index(("release",))
        with psycopg.connect(dsn) as connection:
            table_name, offset = connection.execute(
                "SELECT table_name, applied_offset FROM source_mirror_state.generations WHERE id = %s", (generation_id,),
            ).fetchone()
            assert offset == 0
            assert connection.execute(sql.SQL("SELECT id, body FROM {}").format(
                sql.Identifier("source_mirror", table_name),
            )).fetchall() == [(1, "replacement baseline")]
    finally:
        delivery.close()


@pytest.mark.integration
@pytest.mark.parametrize("case", [
    "response_lost", "pending_loss", "partial_loss", "multi_mirror_loss", "stale_epoch", "inventory_changed_after_reserve",
    "ordinary_authorization", "wrong_request", "wrong_observation", "missing_baseline", "extra_fence_mirror",
    "missing_retained_fence", "missing_loss_receipt", "missing_running_task", "stale_observation", "audit_rollback",
])
def test_runtime_replacement_owner_consumes_committed_recovery(
    management, management_engine, tmp_path, monkeypatch, request, case,
):
    delivery_dsn = request.getfixturevalue("native_target") if case == "response_lost" else None
    transaction, _ = management
    for model in (AuditEventRow, HistoryInvalidationRow, RecoveryRow):
        model.__table__.create(management_engine)
    monkeypatch.setattr(control, "persist_audit_event", persist_audit_event)
    multi_table = case in {"partial_loss", "multi_mirror_loss"}
    order_id = service.enable_for_object("orders", actor_user_id="operator")["mirror"]["id"]
    retained_id = service.enable_for_object("items", actor_user_id="operator")["mirror"]["id"]
    if not multi_table:
        service.set_enabled(retained_id, enabled=False, actor_user_id="operator")
    with transaction() as session:
        for mirror_id in (order_id, retained_id):
            row = session.get(MirrorRow, mirror_id)
            row.state = dict(row.state, published_generation_id=mirror_id + "-published", capture_generation="1")
            session.add(HistoryGateRow(mirror_id=mirror_id, history_epoch="epoch", status="available",
                                       lower_commit_seq=0, lower_entry_seq=0))
    profile = dict(database="db", topic_prefix="cap", tables=["public.orders", "public.items"] if multi_table else ["public.orders"])
    control.reconcile_published_scope(SOURCE)
    with transaction() as session:
        state = load_binding(session, SOURCE)
        state.update(owner_epoch=1, runtime_instance_id="before-loss")
        save_binding(session, state)
        previous = {key: state[key] for key in control.AUTHORITY_KEYS}
        published_scope = state["published_scope"]

    scheduler = Runtime()
    scheduler.validity = "lost"
    if case == "multi_mirror_loss":
        scheduler.affected = [order_id, retained_id]
    history = History(session_factory=sessionmaker(management_engine), target=Target())
    recovery = Recovery(session_factory=sessionmaker(management_engine), history=history,
                        runtime=RuntimeDispatchAdapter(scheduler), retry_delays=(10,))
    action = "run_now" if case == "audit_rollback" else "retry"
    operation_id = recovery.request_recovery(order_id, action=action, expected_history_epoch="epoch",
                                             actor_user_id="operator", reason="test replacement")["operation_id"]
    assert recovery.dispatch(operation_id=operation_id) == "invalidated"
    history.consume_invalidation(operation_id=operation_id)
    scheduler.epoch = recovery.get_operation(operation_id)["replacement_epoch"]
    assert recovery.dispatch(operation_id=operation_id) == "dispatched"
    submission, = scheduler.calls
    assert submission["capture_generation"] == "2"

    with transaction() as session:
        loss = session.get(HistoryInvalidationRow, operation_id)
        transitions = deepcopy(loss.transitions)
        identity = session.get(RecoveryRow, operation_id).identity
        if case == "pending_loss":
            loss.status = "pending"
        if case == "stale_epoch":
            session.get(HistoryGateRow, order_id).history_epoch = "superseded"
    inventory = {
        mirror_id: dict(published_generation_id=mirror_id + "-published", capture_generation="1",
                        history_epoch=scheduler.epoch if mirror_id == order_id else "epoch", history_status="available")
        for mirror_id in (order_id, retained_id)
    }
    scope = dict(profile=profile, published_scope=published_scope, recovery_request_identity=identity,
                 submission=submission, history_loss=transitions, target_inventory=inventory)
    authority = dict(previous, owner_epoch=2, capture_generation=2, runtime_instance_id="replacement",
                     control_revision=previous["control_revision"] + 1)
    key = Ed25519PrivateKey.generate()
    proof = token(key, purpose="owner_allocation" if case == "ordinary_authorization" else "replacement_owner",
                  operation_id=operation_id, authority=authority, scope=scope,
                  previous_authority=previous if case != "wrong_request" else dict(previous, owner_epoch=0))
    request_file = tmp_path / "owner.json"
    request_file.write_text(json.dumps(dict(recovery_operation_id=operation_id, signature=proof)))
    request_file.chmod(0o600)

    observed = []

    def observe(method, path, payload):
        assert (method, path) == ("POST", "/v1/capture/replacement-owner-allocations")
        assert payload["authorization"] == proof
        command = payload["command"]
        observed.append(command)
        with transaction() as session:
            assert load_binding(session, SOURCE)["pending_replacement"] == operation_id
            assert load_operation(session, operation_id) == dict(command=command, evidence=None)
            assert session.get(AuditEventRow, command["replacement"]["issuance_audit_id"]) is not None
        if case in {"response_lost", "inventory_changed_after_reserve"} and len(observed) == 1:
            raise RuntimeBlocked("response_lost")
        if case == "wrong_observation":
            command = dict(command, replacement=dict(command["replacement"], issuance_audit_id="different"))
        fences = {mirror_id: _ref(mirror_id) for mirror_id in inventory}
        if delivery_dsn:
            with psycopg.connect(delivery_dsn) as connection:
                fences[order_id] = bootstrap.prepare_authority(
                    connection, mirror_id=order_id, table_identity="orders", history_epoch=submission["history_epoch"],
                    operation_id=operation_id, expected_authority=None, authority=Authority(**composition._target_authority(command)),
                    exclusion_proof=_ref("fixture-exclusion"), verify_exclusion=lambda *args: True,
                )
        if case == "extra_fence_mirror":
            fences["unexpected"] = _ref("unexpected")
        if case == "missing_retained_fence":
            del fences[retained_id]
        baseline = {field: _ref(field) for field in ("postgresql", "wal", "slot", "connect", "kafka", "task_running")}
        if case == "missing_baseline":
            del baseline["wal"]
        if case == "missing_running_task":
            del baseline["task_running"]
        observation = dict(
            command=command, observed_at="2000-01-01T00:00:00+00:00" if case == "stale_observation" else utc_now().isoformat(),
            checks=dict.fromkeys(CHECKS, "pass"), candidate_baseline=baseline,
            exclusion=dict(method="terminated", **{field: _ref(field) for field in (
                "agent_receipt", "task_receipt", "source_session_receipt", "inflight_drained_receipt"
            )}),
            target_fence=dict(inventory_receipt=_ref("inventory"), mirror_receipts=fences,
                              loss_receipts={} if case == "missing_loss_receipt" else {order_id: _ref("loss")}),
        )
        return dict(signature=token(key, purpose="observation:replacement_owner", operation_id=operation_id,
                                    authority=authority, scope=scope, observation=observation))

    http = Mock(request=Mock(side_effect=observe))
    signals = ReadinessSignals(http, runtime_instance_id="replacement", max_age_seconds=30, required_checks=CHECKS,
                               verifier=verifier(key), scope=profile)
    if case == "audit_rollback":
        def reject_applied_audit(**event):
            record = persist_audit_event(**event)
            if event["action"] == "source.capture_replacement_promoted":
                raise RuntimeBlocked("audit_failed")
            return record

        monkeypatch.setattr(control, "persist_audit_event", reject_applied_audit)

    journal = CommandJournal(tmp_path)
    connect, delivery = Mock(), Mock()
    runtime = CaptureRuntime(journal=journal, connect=connect, signals=signals, delivery=delivery)
    try:
        with pytest.raises(RuntimeBlocked, match="replacement_owner_blocked"):
            runtime.poll_once(SOURCE, replacement_owner_file=request_file)
        with transaction() as session:
            state = load_binding(session, SOURCE)
            assert {name: state[name] for name in previous} == previous
            operation = load_operation(session, operation_id)
            if case in {"pending_loss", "partial_loss", "multi_mirror_loss", "stale_epoch", "ordinary_authorization", "wrong_request"}:
                assert operation is None
                assert not observed
                return
            assert operation["evidence"] is None
            assert session.scalars(select(AuditEventRow).where(
                AuditEventRow.action == "source.capture_replacement_promoted"
            )).all() == []
            if case == "inventory_changed_after_reserve":
                retained = session.get(MirrorRow, retained_id)
                retained.state = dict(retained.state, published_generation_id="different-generation")
        with pytest.raises(SourceCaptureControlConflict):
            control.allocate_owner(source_id=SOURCE, operation_id="ordinary", signed_proof=proof, signals=signals)
        if case == "inventory_changed_after_reserve":
            with pytest.raises(RuntimeBlocked, match="replacement_owner_blocked"):
                runtime.poll_once(SOURCE, replacement_owner_file=request_file)
            assert len(observed) == 1
        if case not in {"response_lost", "audit_rollback"}:
            return

        monkeypatch.setattr(control, "persist_audit_event", persist_audit_event)
        assert runtime.poll_once(SOURCE, replacement_owner_file=request_file) == "applied"
        assert runtime.poll_once(SOURCE, replacement_owner_file=request_file) == "applied"
        assert observed == [operation["command"], operation["command"]]
        with pytest.raises(RuntimeBlocked, match="replacement_owner_requires_recovery"):
            runtime.poll_once(SOURCE)
        with transaction() as session:
            state = load_binding(session, SOURCE)
            assert {name: state[name] for name in authority} == authority
            assert "pending_replacement" not in state
            applied = load_operation(session, operation_id)
            assert state["allocation"] == applied
            assert state["applied_revision"] == authority["control_revision"]
            assert applied["evidence"]["target_fence"]["authority"] == authority
            audit = session.get(AuditEventRow, applied["evidence"]["audit_id"])
            assert audit.detail["issuance_audit_id"] == operation["command"]["replacement"]["issuance_audit_id"]
            assert audit.detail["request_digest"] == sha256(proof.encode()).hexdigest()
            assert audit.detail["observation_digest"] == applied["evidence"]["observation_digest"]

        build_connect = Mock()
        build_delivery = Mock()
        prepare = Mock(return_value=())
        snapshot = Mock()
        runtime = CaptureRuntime(journal=journal, connect=build_connect, signals=signals, delivery=build_delivery,
                                 prepare_delivery=prepare, snapshot=snapshot, profile=Mock(), credentials=Mock())
        snapshot_binding = object()
        build_delivery.snapshot_bindings.return_value = [snapshot_binding]
        mode = "run_now" if action == "run_now" else "window"
        build_delivery.recheck_snapshot_allocation.return_value = (applied["command"], mode)

        def recheck(binding):
            with control.source_control_transaction(SOURCE) as (session, source):
                assert runtime.recheck_snapshot(binding, session=session, source=source) == mode
            return Mock(state="catching_up")

        snapshot.reconcile.side_effect = recheck
        assert runtime.poll_once(SOURCE, replacement_owner_file=request_file) == "idle"
        prepare.assert_called_once_with(applied["command"])
        snapshot.reconcile.assert_called_once_with(snapshot_binding)
        build_delivery.poll_once.assert_called_once_with()
        assert all(call[0] in {"configured", "running"} for call in build_connect.mock_calls)
        assert len(observed) == 2

        if delivery_dsn:
            with monkeypatch.context() as patch:
                _prove_snapshot_delivery(patch, dsn=delivery_dsn, journal=journal, signals=signals,
                                         command=applied["command"], key=key, request_file=request_file)

        with control.source_control_transaction(SOURCE) as (session, source):
            disabled = replace(source, status="disabled")
            get_source_store().save_source_on(session, disabled)
            control.record_source_intent(session, source, disabled, actor_user_id="operator", actor_token_id=None)

        def stop_observation(command, phase):
            assert command["kind"] == "stop"
            assert command["owner_epoch"] == 2
            assert command["capture_generation"] == 2
            if phase == "stopped":
                return dict({name: command[name] for name in control.AUTHORITY_KEYS},
                            operation_id=command["operation_id"], observed_at=utc_now().isoformat(), **{
                    name: _ref(name) for name in (
                        "target_fence_ref", "owner_exclusion_ref", "retired_commands_rejected_ref",
                        "task_stopped_ref", "source_session_stopped_ref", "inflight_drained_ref",
                    )
                })

        monkeypatch.setattr(signals, "observation", stop_observation)
        build_connect.stopped.side_effect = [False, True]
        assert runtime.poll_once(SOURCE, replacement_owner_file=request_file) == "applied"
        build_connect.stop.assert_called_once_with()
        snapshot.reconcile.assert_called_once_with(snapshot_binding)
        with transaction() as session:
            assert load_binding(session, SOURCE)["stop_ack"]["owner_epoch"] == 2
    finally:
        assert not connect.mock_calls
        delivery.poll_once.assert_not_called()
        journal.close()
