from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
import os
from uuid import uuid4

import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core import db
from backend.core.config import reset_settings_cache
from backend.core.time import utc_now
from backend.metadata.capture import configuration, snapshot
from backend.metadata.capture.authority import SignedAuthority
from backend.metadata.capture.control import source_control_transaction
from backend.metadata.capture.runtime_store import CommandJournal, RuntimeBlocked
from backend.metadata.capture.snapshot import SnapshotBinding, SnapshotCoordinator
from backend.metadata.capture.store import load_binding, save_binding
from backend.metadata.mirrors.models import MirrorRow
from backend.metadata.mirrors.types import Authority, PartitionIdentity
from backend.metadata.models import SourceCaptureBindingRow, SourceRow
from backend.metadata.sources.store import SourceRecord, get_source_store, reset_source_store


class SignalFixture:
    def __init__(self):
        self.keys = {role: Ed25519PrivateKey.generate() for role in ("receipt", "notifications")}
        self.signals = []
        self.response_lost = False
        self.receipt_visible = False
        self.records = []
        self.notification_token = None
        self.last_notification_token = None
        self.replay_offset = None
        self.receipt_signer = "receipt"
        self.receipt_evidence = None
        self.batch_limit = None
        self.baseline_token = None
        self.last_baseline_token = None

    def trust(self, role):
        return SignedAuthority(keys={role: self.keys[role].public_key()}, issuer=role, audience="capture")

    def signed(self, role, purpose, binding, operation_id, evidence, *, age=0, challenge=None):
        now = utc_now() - timedelta(seconds=age)
        return jwt.encode({
            "iss": role, "aud": "capture", "iat": now, "nbf": now,
            "exp": now + timedelta(minutes=2), "jti": uuid4().hex,
            "purpose": purpose, "authority": asdict(binding.authority),
            "scope": asdict(binding), "operation_id": operation_id, "evidence": evidence, "challenge": challenge,
        }, self.keys[role], algorithm="EdDSA", headers={"kid": role})

    def baseline(self, binding, operation_id, *, challenge=None):
        if self.baseline_token is not None:
            return self.baseline_token
        self.last_baseline_token = self.signed("notifications", "snapshot:baseline", binding, operation_id,
                                               {"offset": 9, "idle": True, "exclusive": True}, challenge=challenge)
        return self.last_baseline_token

    def submit(self, binding, signal):
        self.signals.append((binding, signal))
        if self.response_lost:
            raise TimeoutError

    def receipt(self, binding, operation_id):
        if not self.receipt_visible:
            return None
        assert self.signals[0][0] == binding
        return self.signed(self.receipt_signer, "snapshot:receipt", binding, operation_id,
                           self.receipt_evidence if self.receipt_evidence is not None else self.signals[0][1])

    def notifications(self, binding, operation_id, offset, *, challenge=None):
        if self.notification_token is not None:
            if callable(self.notification_token):
                return self.notification_token(challenge)
            return self.notification_token
        if self.replay_offset is not None:
            offset = self.replay_offset
        records = [record for record in self.records if record["offset"] >= offset]
        high_water = offset + len(records)
        records = records[:self.batch_limit]
        self.last_notification_token = self.signed("notifications", "snapshot:notifications", binding, operation_id, {
            "start": offset, "end": offset + len(records), "high_water": high_water,
            "records": records, "exclusive": True,
        }, challenge=challenge)
        return self.last_notification_token

    def native(self, binding, operation_id, offset, kind, **data):
        return {"offset": offset, "key": {"id": operation_id}, "value": {
            "id": operation_id, "aggregate_type": "Incremental Snapshot", "type": kind,
            "timestamp": int(utc_now().timestamp() * 1000),
            "additional_data": {"connector_name": binding.connector_name} | data,
        }}

    def beginning(self, binding, operation_id, *, offset=9):
        return [
            self.native(binding, operation_id, offset, "STARTED", data_collections=binding.qualified_table),
            self.native(binding, operation_id, offset + 1, "DATA_COLLECTIONS_RESOLVED",
                        data_collections=binding.qualified_table),
        ]


@pytest.fixture(params=["memory", "postgresql"])
def prepared(monkeypatch, request):
    if request.param == "postgresql":
        dsn = os.getenv("REFRAQ_SNAPSHOT_TEST_DSN")
        if not dsn:
            pytest.skip("Set REFRAQ_SNAPSHOT_TEST_DSN to a disposable PostgreSQL instance")
        database = "snapshot_" + uuid4().hex
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(dsn, dbname=database))
        monkeypatch.setattr(db, "get_session_factory", lambda: sessionmaker(bind=engine))

        def cleanup():
            engine.dispose()
            with psycopg.connect(dsn, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))

        request.addfinalizer(cleanup)
        SourceRow.__table__.create(engine)
        SourceCaptureBindingRow.__table__.create(engine)
        MirrorRow.__table__.create(engine)
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "persistent" if request.param == "postgresql" else "memory")
    reset_settings_cache()
    reset_source_store()
    authority = Authority("source-one", "binding-one", 2, "owner-two", 3, 1, "1")
    binding = SnapshotBinding(
        authority=authority, mirror_id="mirror-one", mirror_revision=4, allocation_operation_id="open-one",
        generation_id="generation-one", table_identity="table-one", qualified_table="public.orders",
        history_epoch="history-one", schema_fingerprint="schema-one",
        data_partition=PartitionIdentity("broker-one", "orders-incarnation", 0), connector_name="logical-source-one",
        signal_table="public.snapshot_signal", signal_relation_identity="registered-signal-relation",
        notification_topic="logical-source-one.notifications",
        notification_partition=PartitionIdentity("broker-one", "notification-incarnation", 0),
    )
    other = replace(binding, mirror_id="mirror-two", allocation_operation_id="open-two",
                    generation_id="generation-two", table_identity="table-two", qualified_table="public.other",
                    data_partition=PartitionIdentity("broker-one", "other-incarnation", 0))
    now = utc_now()
    get_source_store().create_source(SourceRecord(
        id=authority.source_id, key="one", locator_key="one", name="One", kind="database",
        status="active", description=None, engine="postgresql", access_ciphertext=None,
        access_updated_at=None, created_at=now, updated_at=now, capture_revision=1,
        capture_credential_ciphertext="sealed",
    ))
    with source_control_transaction(authority.source_id) as (session, source):
        stamps = asdict(authority)
        stamps["binding_id"] = stamps.pop("resource_binding_id")
        save_binding(session, dict(stamps, capture_generation=1, desired="configured", applied_revision=3,
                                   published_scope=[{key: getattr(candidate, key) for key in (
                                       "mirror_id", "mirror_revision", "table_identity", "qualified_table"
                                   )} | {"included": True} for candidate in (binding, other)]))
    yield binding, other
    reset_source_store()
    reset_settings_cache()


def coordinator(tmp_path, signals, **options):
    return SnapshotCoordinator(
        journal=CommandJournal(tmp_path), signals=signals, receipt_trust=signals.trust("receipt"),
        notification_trust=signals.trust("notifications"), max_observation_age_seconds=30,
        **({"recheck": lambda binding, *, session, source: "window"} | options),
    )


def test_lost_response_recovers_one_exact_operation_and_blocks_the_next_table(tmp_path, prepared):
    binding, other = prepared
    signals = SignalFixture()
    signals.response_lost = True
    initial = coordinator(tmp_path, signals)
    try:
        pending = initial.reconcile(binding)
        assert pending.state == "submission_uncertain"
    finally:
        initial.journal.close()
    restarted = coordinator(tmp_path, signals)
    try:
        assert restarted.reconcile(binding) == pending
        assert restarted.reconcile(other).state == "source_busy"
    finally:
        restarted.journal.close()
    assert signals.signals == [(binding, {
        "id": pending.operation_id, "type": "execute-snapshot",
        "data": {"type": "incremental", "data-collections": [r"public\.orders"]},
    })]


def test_receipt_and_both_native_terminals_are_required_for_catch_up(tmp_path, prepared):
    binding, other = prepared
    signals = SignalFixture()
    worker = coordinator(tmp_path, signals)
    try:
        pending = worker.reconcile(binding)
        operation_id = pending.operation_id
        signals.records.extend(signals.beginning(binding, operation_id))
        signals.records.append(signals.native(binding, operation_id, 11, "TABLE_SCAN_COMPLETED",
                                               scanned_collection="public.orders", status="EMPTY",
                                               total_rows_scanned="0"))
        assert worker.reconcile(binding).state != "catching_up"
        signals.records.append(signals.native(binding, operation_id, 12, "COMPLETED"))
        assert worker.reconcile(binding).state != "catching_up"
        signals.receipt_visible = True
        completed = worker.reconcile(binding)
        assert completed.state == "catching_up"
        assert completed.operation_id == operation_id
        assert (completed.scan_offset, completed.completion_offset) == (11, 12)
        assert worker.reconcile(binding) == completed
        assert worker.reconcile(other).state == "submission_uncertain"
        assert len(signals.signals) == 2
    finally:
        worker.journal.close()


def test_reopened_table_waits_for_terminal_proof_of_its_abandoned_scan(tmp_path, prepared):
    binding, _ = prepared
    signals = SignalFixture()
    worker = coordinator(tmp_path, signals)
    try:
        old = worker.reconcile(binding).operation_id
        reopened = replace(binding, mirror_revision=binding.mirror_revision + 2,
                           allocation_operation_id="reopened", generation_id="fresh-generation",
                           authority=replace(binding.authority, control_revision=binding.authority.control_revision + 2))
        source_id = binding.authority.source_id
        with source_control_transaction(source_id) as (session, _):
            state = load_binding(session, source_id)
            state.update(control_revision=reopened.authority.control_revision, applied_revision=reopened.authority.control_revision)
            state["published_scope"][0]["mirror_revision"] = reopened.mirror_revision
            save_binding(session, state)
        assert worker.reconcile(reopened).state == "source_busy"
        signals.receipt_visible = True
        signals.records.extend(signals.beginning(binding, old))
        signals.records.append(signals.native(binding, old, 11, "TABLE_SCAN_COMPLETED",
                                             scanned_collection=binding.qualified_table, status="EMPTY", total_rows_scanned="0"))
        assert worker.reconcile(reopened).state == "source_busy"
        assert len(signals.signals) == 1
        signals.records.append(signals.native(binding, old, 12, "COMPLETED"))
        assert worker.reconcile(reopened).state == "source_busy"
        with source_control_transaction(source_id) as (session, _):
            ledger = load_binding(session, source_id)["incremental_snapshots"]
            assert ledger["active"] is None
            previous = ledger["generations"][binding.generation_id]
            assert previous["state"] == "abandoned" and previous["released_at"]
        assert worker.reconcile(reopened).state == "submission_uncertain"
        assert len(signals.signals) == 2
    finally:
        worker.journal.close()


def test_excluded_scan_releases_slot_while_sibling_has_no_snapshot_work(tmp_path, prepared):
    binding, _ = prepared
    signals = SignalFixture()
    worker = coordinator(tmp_path, signals)
    try:
        operation = worker.reconcile(binding).operation_id
        source_id = binding.authority.source_id
        with source_control_transaction(source_id) as (session, _):
            state = load_binding(session, source_id)
            state["published_scope"][0].update(included=False, mirror_revision=binding.mirror_revision + 1)
            save_binding(session, state)
        signals.receipt_visible = True
        signals.records.extend(signals.beginning(binding, operation))
        signals.records.append(signals.native(binding, operation, 11, "TABLE_SCAN_COMPLETED",
                                             scanned_collection=binding.qualified_table, status="EMPTY", total_rows_scanned="0"))
        worker.poll_abandoned_slot(source_id)
        with source_control_transaction(source_id) as (session, _):
            assert load_binding(session, source_id)["incremental_snapshots"]["active"] == binding.generation_id
        signals.records.append(signals.native(binding, operation, 12, "COMPLETED"))
        worker.poll_abandoned_slot(source_id)
        with source_control_transaction(source_id) as (session, _):
            assert load_binding(session, source_id)["incremental_snapshots"]["active"] is None
        assert len(signals.signals) == 1
    finally:
        worker.journal.close()


def test_signed_table_progress_keeps_observed_bytes_across_the_terminal(tmp_path, prepared):
    binding, _ = prepared
    signals = SignalFixture()
    worker = coordinator(tmp_path, signals)
    try:
        op = worker.reconcile(binding).operation_id
        signals.receipt_visible = True
        signals.records.extend(signals.beginning(binding, op))
        signals.records.append(signals.native(binding, op, 11, "IN_PROGRESS",
                                              current_collection_in_progress=binding.qualified_table,
                                              scanned_bytes="320", scan_total_bytes="1000"))
        assert worker.reconcile(binding).state == "snapshotting"
        signals.records.extend([
            signals.native(binding, op, 12, "IN_PROGRESS", current_collection_in_progress=binding.qualified_table,
                           scanned_bytes="450"),
            signals.native(binding, op, 13, "IN_PROGRESS", current_collection_in_progress=binding.qualified_table,
                           scanned_bytes="319", scan_total_bytes="999"),
            signals.native(binding, op, 14, "TABLE_SCAN_COMPLETED", scanned_collection=binding.qualified_table,
                           status="SUCCEEDED", total_rows_scanned="1"),
            signals.native(binding, op, 15, "COMPLETED"),
        ])
        assert worker.reconcile(binding).state == "catching_up"
        with source_control_transaction(binding.authority.source_id) as (session, source):
            ledger = load_binding(session, source.id)["incremental_snapshots"]
            operation = ledger["generations"][binding.generation_id]
        assert operation["byte_sample"] == dict(offset=12, timestamp=signals.records[-4]["value"]["timestamp"],
                                                scanned_bytes=450, scan_total_bytes=1000)
        assert operation["progress_sample"]["offset"] == operation["scan"]["offset"] == 14
        assert ledger["active"] is None
    finally:
        worker.journal.close()


def test_legacy_bytes_keep_unknown_provenance_until_measured_again(tmp_path, prepared):
    binding, _ = prepared
    signals = SignalFixture()
    worker = coordinator(tmp_path, signals)
    try:
        op = worker.reconcile(binding).operation_id
        signals.receipt_visible = True
        signals.records.extend(signals.beginning(binding, op))
        assert worker.reconcile(binding).state == "snapshotting"
        with source_control_transaction(binding.authority.source_id) as (session, source):
            state = load_binding(session, source.id)
            legacy = state["incremental_snapshots"]["generations"][binding.generation_id]["progress_sample"]
            legacy.update(scanned_bytes=300, scan_total_bytes=1000)
            save_binding(session, state)
        for offset, measured in ((11, None), (12, "400")):
            data = {"scanned_bytes": measured} if measured else {}
            signals.records.append(signals.native(binding, op, offset, "IN_PROGRESS",
                                                  current_collection_in_progress=binding.qualified_table, **data))
            assert worker.reconcile(binding).state == "snapshotting"
            with source_control_transaction(binding.authority.source_id) as (session, source):
                state = load_binding(session, source.id)
                operation = state["incremental_snapshots"]["generations"][binding.generation_id]
            assert operation["progress_sample"]["offset"] == offset
            if measured is None:
                assert operation["byte_sample"] == dict(scanned_bytes=300, scan_total_bytes=1000)
            else:
                assert operation["byte_sample"] == dict(scanned_bytes=400, scan_total_bytes=1000, offset=offset,
                                                        timestamp=signals.records[-1]["value"]["timestamp"])
    finally:
        worker.journal.close()


def test_window_is_rechecked_after_the_durable_claim(tmp_path, prepared, monkeypatch):
    binding, _ = prepared
    source = get_source_store().get_source(binding.authority.source_id)
    get_source_store().save_source(replace(source, snapshot_window={"start": "23:00", "end": "01:00"}))
    monkeypatch.setattr(configuration, "current_schedule_timezone", lambda: "Asia/Shanghai")
    instants = iter(datetime(2026, 1, 1, hour, tzinfo=UTC) for hour in (16, 17))
    signals = SignalFixture()
    worker = coordinator(tmp_path, signals, dispatch_clock=lambda: next(instants))
    try:
        postponed = worker.reconcile(binding)
        assert postponed.state == "waiting_window"
        assert postponed.operation_id
        assert signals.signals == []
        worker.dispatch_clock = lambda: datetime(2026, 1, 2, 16, tzinfo=UTC)
        assert worker.reconcile(binding).operation_id == postponed.operation_id
        assert signals.signals[0][1]["id"] == postponed.operation_id
    finally:
        worker.journal.close()


@pytest.mark.parametrize("fault", ["foreign_id", "connector", "wrong_table", "failed_scan", "gap", "aggregate_first"])
def test_inconsistent_authenticated_notifications_keep_the_source_unavailable(tmp_path, prepared, fault):
    binding, other = prepared
    signals = SignalFixture()
    worker = coordinator(tmp_path, signals)
    try:
        operation_id = worker.reconcile(binding).operation_id
        scan = signals.native(binding, operation_id, 11, "TABLE_SCAN_COMPLETED",
                              scanned_collection="public.orders", status="SUCCEEDED", total_rows_scanned="4")
        complete = signals.native(binding, operation_id, 12, "COMPLETED")
        if fault == "foreign_id":
            complete["value"]["id"] = "foreign"
        elif fault == "connector":
            scan["value"]["additional_data"]["connector_name"] = "other-connector"
        elif fault == "wrong_table":
            scan["value"]["additional_data"]["scanned_collection"] = "public.other"
        elif fault == "failed_scan":
            scan["value"]["additional_data"]["status"] = "ABORTED"
        elif fault == "gap":
            complete["offset"] = 13
        elif fault == "aggregate_first":
            scan, complete = complete | {"offset": 11}, scan | {"offset": 12}
        signals.records = signals.beginning(binding, operation_id) + [scan, complete]
        signals.receipt_visible = True
        blocked = worker.reconcile(binding)
        assert blocked.state == "blocked"
        assert blocked.scan_offset is None
        assert worker.reconcile(other).state == "source_busy"
    finally:
        worker.journal.close()


def test_replayed_notifications_do_not_prove_current_exclusion_or_advance_the_cursor(tmp_path, prepared):
    binding, _ = prepared
    signals = SignalFixture()
    worker = coordinator(tmp_path, signals)
    try:
        operation_id = worker.reconcile(binding).operation_id
        signals.records = signals.beginning(binding, operation_id) + [
            signals.native(binding, operation_id, 11, "TABLE_SCAN_COMPLETED",
                           scanned_collection="public.orders", status="SUCCEEDED", total_rows_scanned="4"),
            signals.native(binding, operation_id, 12, "COMPLETED"),
        ]
        assert worker.reconcile(binding).state == "submission_uncertain"
        signals.receipt_visible = True
        signals.replay_offset = 9
        assert worker.reconcile(binding).state == "snapshotting"
        signals.replay_offset = None
        assert worker.reconcile(binding).state == "catching_up"
    finally:
        worker.journal.close()


def test_notification_authority_cannot_attest_the_submission_receipt(tmp_path, prepared):
    binding, _ = prepared
    signals = SignalFixture()
    worker = coordinator(tmp_path, signals)
    try:
        pending = worker.reconcile(binding)
        signals.receipt_visible = True
        signals.receipt_signer = "notifications"
        with pytest.raises(RuntimeBlocked, match="signed_authority_unverified"):
            worker.reconcile(binding)
        signals.receipt_signer = "receipt"
        assert worker.reconcile(binding).state == "snapshotting"
        assert signals.signals[0][1]["id"] == pending.operation_id
    finally:
        worker.journal.close()


def test_wrong_scope_or_stale_signed_notification_cannot_establish_completion(tmp_path, prepared):
    binding, _ = prepared
    signals = SignalFixture()
    worker = coordinator(tmp_path, signals)
    try:
        operation_id = worker.reconcile(binding).operation_id
        evidence = {"start": 9, "end": 9, "high_water": 9, "records": [], "exclusive": True}
        signals.notification_token = lambda challenge: signals.signed(
            "notifications", "snapshot:notifications", replace(binding, generation_id="foreign"), operation_id, evidence,
            challenge=challenge,
        )
        with pytest.raises(RuntimeBlocked, match="signed_authority_unverified"):
            worker.reconcile(binding)
        signals.notification_token = lambda challenge: signals.signed(
            "notifications", "snapshot:notifications", binding, operation_id, evidence, age=45,
            challenge=challenge,
        )
        with pytest.raises(RuntimeBlocked, match="snapshot_evidence_stale_or_invalid"):
            worker.reconcile(binding)
    finally:
        worker.journal.close()


def test_previously_signed_empty_batch_cannot_finalize_a_later_poll(tmp_path, prepared):
    binding, _ = prepared
    signals = SignalFixture()
    worker = coordinator(tmp_path, signals)
    try:
        operation_id = worker.reconcile(binding).operation_id
        signals.records = signals.beginning(binding, operation_id) + [
            signals.native(binding, operation_id, 11, "TABLE_SCAN_COMPLETED",
                           scanned_collection="public.orders", status="EMPTY", total_rows_scanned="0"),
            signals.native(binding, operation_id, 12, "COMPLETED"),
        ]
        assert worker.reconcile(binding).state == "submission_uncertain"
        assert worker.reconcile(binding).state == "submission_uncertain"
        signals.notification_token = signals.last_notification_token
        signals.receipt_visible = True
        with pytest.raises(RuntimeBlocked, match="snapshot_notification_observation_replayed"):
            worker.reconcile(binding)
        signals.notification_token = None
        assert worker.reconcile(binding).state == "catching_up"
    finally:
        worker.journal.close()


def test_conflicting_durable_receipt_keeps_the_source_blocked(tmp_path, prepared):
    binding, other = prepared
    signals = SignalFixture()
    worker = coordinator(tmp_path, signals)
    try:
        operation_id = worker.reconcile(binding).operation_id
        signals.receipt_visible = True
        signals.receipt_evidence = {"id": operation_id, "type": "execute-snapshot",
                                    "data": {"type": "incremental", "data-collections": [r"public\.other"]}}
        assert worker.reconcile(binding).state == "blocked"
        assert worker.reconcile(other).state == "source_busy"
        assert len(signals.signals) == 1
    finally:
        worker.journal.close()


def test_matching_terminals_do_not_complete_a_partial_notification_batch(tmp_path, prepared):
    binding, other = prepared
    signals = SignalFixture()
    worker = coordinator(tmp_path, signals)
    try:
        operation_id = worker.reconcile(binding).operation_id
        signals.receipt_visible = True
        signals.records = signals.beginning(binding, operation_id) + [
            signals.native(binding, operation_id, 11, "TABLE_SCAN_COMPLETED",
                           scanned_collection="public.orders", status="SUCCEEDED", total_rows_scanned="4"),
            signals.native(binding, operation_id, 12, "COMPLETED"),
            signals.native(binding, "external-operation", 13, "STARTED", data_collections="public.orders"),
        ]
        signals.batch_limit = 4
        assert worker.reconcile(binding).state == "snapshotting"
        assert worker.reconcile(binding).state == "blocked"
        assert worker.reconcile(other).state == "source_busy"
    finally:
        worker.journal.close()


def test_receipt_and_notification_verifiers_require_distinct_keys(tmp_path):
    signals = SignalFixture()
    signals.keys["receipt"] = signals.keys["notifications"]
    journal = CommandJournal(tmp_path)
    try:
        with pytest.raises(RuntimeBlocked, match="snapshot_independent_observers_required"):
            SnapshotCoordinator(journal=journal, signals=signals, recheck=None,
                                max_observation_age_seconds=30, receipt_trust=signals.trust("receipt"),
                                notification_trust=signals.trust("notifications"))
    finally:
        journal.close()


@pytest.mark.parametrize("fault", ["missing_start", "backdated_completion", "restart_after_scan"])
def test_terminal_pair_requires_one_observed_scan_attempt(tmp_path, prepared, fault):
    binding, other = prepared
    signals = SignalFixture()
    signals.receipt_visible = True
    worker = coordinator(tmp_path, signals)
    try:
        operation_id = worker.reconcile(binding).operation_id
        records = signals.beginning(binding, operation_id) if fault != "missing_start" else []
        scan = signals.native(binding, operation_id, 9 + len(records), "TABLE_SCAN_COMPLETED",
                              scanned_collection=binding.qualified_table, status="EMPTY", total_rows_scanned="0")
        records.append(scan)
        if fault == "restart_after_scan":
            skipped = signals.native(binding, "bootstrap", 9 + len(records), "SKIPPED")
            skipped["value"]["aggregate_type"] = "Initial Snapshot"
            records.append(skipped)
        complete = signals.native(binding, operation_id, 9 + len(records), "COMPLETED")
        if fault == "backdated_completion":
            complete["value"]["timestamp"] = scan["value"]["timestamp"] - 1000
        signals.records = [*records, complete]
        assert worker.reconcile(binding).state == "blocked"
        assert worker.reconcile(other).state == "source_busy"
    finally:
        worker.journal.close()


def test_restart_before_the_first_scan_reuses_operation_and_resolves_the_same_table(tmp_path, prepared):
    binding, _ = prepared
    signals = SignalFixture()
    worker = coordinator(tmp_path, signals)
    try:
        operation_id = worker.reconcile(binding).operation_id
        signals.records = signals.beginning(binding, operation_id)
        assert worker.reconcile(binding).state == "submission_uncertain"
    finally:
        worker.journal.close()

    restarted = coordinator(tmp_path, signals)
    try:
        skipped = signals.native(binding, "bootstrap", 11, "SKIPPED")
        skipped["value"]["aggregate_type"] = "Initial Snapshot"
        signals.records += [skipped, *signals.beginning(binding, operation_id, offset=12),
                            signals.native(binding, operation_id, 14, "IN_PROGRESS",
                                           current_collection_in_progress=binding.qualified_table),
                            signals.native(binding, operation_id, 15, "TABLE_SCAN_COMPLETED",
                                           scanned_collection=binding.qualified_table, status="SUCCEEDED",
                                           total_rows_scanned="3"),
                            signals.native(binding, operation_id, 16, "COMPLETED")]
        signals.receipt_visible = True
        result = restarted.reconcile(binding)
        assert (result.operation_id, result.state, result.scan_offset, result.completion_offset) == (
            operation_id, "catching_up", 15, 16,
        )
        assert len(signals.signals) == 1
    finally:
        restarted.journal.close()


def test_changed_claim_cannot_send_or_release_source(tmp_path, prepared, monkeypatch):
    binding, other = prepared
    signals = SignalFixture()
    (tmp_path / "claimant").mkdir(mode=0o700)
    (tmp_path / "observer").mkdir(mode=0o700)
    worker = coordinator(tmp_path / "claimant", signals)
    observer = coordinator(tmp_path / "observer", signals)
    original_transaction = snapshot.source_control_transaction
    interleave = True

    @contextmanager
    def transaction(source_id):
        nonlocal interleave
        with original_transaction(source_id) as (session, source):
            yield session, source
            ledger = load_binding(session, source_id)["incremental_snapshots"]
        if interleave:
            interleave = False
            operation_id = ledger["generations"][binding.generation_id]["id"]
            signals.records = signals.beginning(binding, operation_id)
            assert observer.reconcile(binding).state == "submission_uncertain"

    monkeypatch.setattr(snapshot, "source_control_transaction", transaction)
    try:
        result = worker.reconcile(binding)
        assert result.state == "blocked"
        assert observer.reconcile(other).state == "source_busy"
        assert signals.signals == []
    finally:
        observer.journal.close()
        worker.journal.close()


def test_window_retry_requires_a_fresh_baseline_for_the_same_operation(tmp_path, prepared, monkeypatch):
    binding, _ = prepared
    source = get_source_store().get_source(binding.authority.source_id)
    get_source_store().save_source(replace(source, snapshot_window={"start": "00:00", "end": "01:00"}))
    monkeypatch.setattr(configuration, "current_schedule_timezone", lambda: "UTC")
    instants = iter(datetime(2026, 1, 1, hour, tzinfo=UTC) for hour in (0, 1, 0, 0, 0))
    signals = SignalFixture()
    worker = coordinator(tmp_path, signals, dispatch_clock=lambda: next(instants))
    try:
        deferred = worker.reconcile(binding)
        assert deferred.state == "waiting_window"
        signals.baseline_token = signals.last_baseline_token
        with pytest.raises(RuntimeBlocked, match="snapshot_notification_observation_replayed"):
            worker.reconcile(binding)
        assert signals.signals == []
        signals.baseline_token = None
        assert worker.reconcile(binding).operation_id == deferred.operation_id
        assert len(signals.signals) == 1
    finally:
        worker.journal.close()


def test_baseline_aging_before_dispatch_allows_retry_of_the_original_operation(tmp_path, prepared, monkeypatch):
    binding, _ = prepared
    signals = SignalFixture()
    worker = coordinator(tmp_path, signals)
    original_transaction = snapshot.source_control_transaction

    @contextmanager
    def transaction(source_id):
        with original_transaction(source_id) as transaction_context:
            yield transaction_context
        patch.setattr(snapshot, "utc_now", lambda: utc_now() + timedelta(seconds=60))

    try:
        with monkeypatch.context() as patch:
            patch.setattr(snapshot, "source_control_transaction", transaction)
            with pytest.raises(RuntimeBlocked, match="snapshot_evidence_stale_or_invalid"):
                worker.reconcile(binding)
        assert signals.signals == []
        with original_transaction(binding.authority.source_id) as (session, _):
            ledger = load_binding(session, binding.authority.source_id)["incremental_snapshots"]
        operation_id = ledger["generations"][binding.generation_id]["id"]
        assert ledger["active"] is None
        retried = worker.reconcile(binding)
        assert (retried.operation_id, retried.state) == (operation_id, "submission_uncertain")
        assert len(signals.signals) == 1
    finally:
        worker.journal.close()


def test_challenged_prefix_replay_cannot_discard_a_higher_sampled_boundary(tmp_path, prepared):
    binding, _ = prepared
    signals = SignalFixture()
    worker = coordinator(tmp_path, signals)
    try:
        operation_id = worker.reconcile(binding).operation_id
        signals.records = signals.beginning(binding, operation_id) + [
            signals.native(binding, operation_id, 11, "TABLE_SCAN_COMPLETED",
                           scanned_collection=binding.qualified_table, status="EMPTY", total_rows_scanned="0"),
            signals.native(binding, operation_id, 12, "COMPLETED"),
        ]
        assert worker.reconcile(binding).state == "submission_uncertain"
        signals.receipt_visible = True
        signals.replay_offset = 9
        signals.batch_limit = 4
        signals.records.append(signals.native(binding, "foreign", 13, "STARTED",
                                              data_collections=binding.qualified_table))
        assert worker.reconcile(binding).state == "snapshotting"
        signals.records.pop()
        signals.replay_offset = None
        assert worker.reconcile(binding).state == "blocked"
    finally:
        worker.journal.close()


def test_trust_key_mutation_cannot_turn_notification_signer_into_receipt_observer(tmp_path, prepared):
    binding, _ = prepared
    signals = SignalFixture()
    journal = CommandJournal(tmp_path)
    receipt_trust = signals.trust("receipt")
    worker = SnapshotCoordinator(journal=journal, signals=signals, receipt_trust=receipt_trust,
                                 notification_trust=signals.trust("notifications"), max_observation_age_seconds=30,
                                 recheck=lambda binding, *, session, source: "window")
    try:
        worker.reconcile(binding)
        signals.keys["receipt"] = signals.keys["notifications"]
        receipt_trust.keys["receipt"] = signals.keys["receipt"].public_key()
        signals.receipt_visible = True
        with pytest.raises(RuntimeBlocked, match="signed_authority_unverified"):
            worker.reconcile(binding)
    finally:
        journal.close()
