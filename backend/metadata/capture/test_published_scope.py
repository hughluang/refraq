"""Published mirror scope through the management transaction and capture runtime."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
import json
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.core.config import get_settings
from backend.core.secrets import encrypt_secret
from backend.core.time import FixedClock, get_clock, set_clock, utc_now
from backend.metadata.capture import control, delivery_composition, runtime as entrypoint
from backend.metadata.capture.postgresql import PostgreSQLCaptureProfile
from backend.metadata.capture.runtime import CaptureRuntime
from backend.metadata.capture.runtime_store import CommandJournal, RuntimeBlocked
from backend.metadata.capture.store import save_binding
from backend.metadata.capture.test_delivery import KEY, SCHEMA
from backend.metadata.capture.test_runtime import CHECKS, SIGNING_KEY, allocation_observation, observation
from backend.metadata.mirrors import service
from backend.metadata.mirrors.diagnostic_store import DiagnosticRow
from backend.metadata.mirrors.models import MirrorOperationRow, MirrorRow
from backend.metadata.mirrors.store import SqlMirrorStore
from backend.metadata.models import CatalogObjectRow, SourceCaptureBindingRow, SourceCaptureOperationRow, SourceRow
from backend.metadata.sources.store import SourceRecord, get_source_store, reset_source_store
from backend.tests.mirror_inventory import inventory


SOURCE = "source-one"


def pending_capture_commands():
    with control.source_control_transaction(SOURCE) as (session, _):
        binding = control.load_binding(session, SOURCE)
        return tuple(op["command"] for op in control.list_operations(session, SOURCE)
                     if binding is not None and op["evidence"] is None
                     and op["command"]["control_revision"] == binding["control_revision"])


@pytest.fixture
def management_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'management.sqlite3'}")
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def management(monkeypatch, request, management_engine):
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "persistent")
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "offline-scope-fixture")
    monkeypatch.setenv("DATABASE_URL", "postgresql://fixture/management?sslmode=verify-full")
    monkeypatch.setenv("REDIS_URL", "redis://fixture/0")
    get_settings.cache_clear()
    reset_source_store()
    request.addfinalizer(get_settings.cache_clear)
    request.addfinalizer(reset_source_store)
    engine = management_engine
    for model in (SourceRow, CatalogObjectRow, SourceCaptureBindingRow, SourceCaptureOperationRow, MirrorRow,
                  MirrorOperationRow, service.HistoryGateRow, DiagnosticRow):
        model.__table__.create(engine)
    factory = sessionmaker(engine)

    @contextmanager
    def transaction():
        with factory.begin() as session:
            yield session

    class Store(SqlMirrorStore):
        def transaction(self):
            return transaction()

    monkeypatch.setattr(control, "session_scope", transaction)
    monkeypatch.setattr(control, "persist_audit_event", lambda **kwargs: None)
    monkeypatch.setattr(service, "persist_audit_event", lambda **kwargs: None)
    monkeypatch.setattr(service, "_store", Store())
    monkeypatch.setattr(service, "_target", None)
    now = utc_now()
    source = SourceRecord(
        id=SOURCE, key="one", locator_key="pg://one", name="One", kind="database",
        status="active", description=None, engine="postgresql",
        access_ciphertext=encrypt_secret(json.dumps(dict(host="pg.internal", port=5432, database="db", schema="public"))),
        access_updated_at=None, created_at=now, updated_at=now,
        capture_credential_ciphertext=encrypt_secret(json.dumps(dict(username="capture", password="fixture"))),
        capture_revision=1,
    )
    if getattr(request, "param", None) == "without_credentials":
        source = replace(source, capture_credential_ciphertext=None, capture_revision=0)
    with transaction() as session:
        source = get_source_store().create_source_on(session, source)
        control.record_source_intent(session, None, source, actor_user_id=None, actor_token_id=None)
        session.add_all([CatalogObjectRow(
            id=name, source_id=SOURCE, locator_key=name, object_type="table", schema_name="public",
            name=name, created_at=now, updated_at=now,
        ) for name in ("items", "orders")])
    yield transaction, source


def test_explicit_open_becomes_current_capture_command(management, tmp_path):
    orders = service.enable_for_object("orders", actor_user_id="operator")["mirror"]
    journal = CommandJournal(tmp_path)
    runtime = CaptureRuntime(journal=journal, connect=None, signals=None)
    try:
        with pytest.raises(RuntimeBlocked, match="owner_assignment_unproven"):
            runtime.poll_once(SOURCE)
        command, = pending_capture_commands()
        assert command["kind"] == "reconcile"
        assert command["control_revision"] == 2
        assert command["published_scope"] == [{
            "mirror_id": orders["id"], "table_identity": "orders",
            "qualified_table": "public.orders", "mirror_revision": 1, "included": True,
        }]
        mirror = service.get_mirror(orders["id"])
        assert mirror["operations"][0]["state"] == "pending"
        assert mirror["published_generation_id"] is None
    finally:
        journal.close()


@pytest.mark.parametrize("case", ["partial_scope", "superseded_revision"])
def test_applied_open_preparation_requires_current_complete_scope(management, monkeypatch, case):
    transaction, _ = management
    mirror_id = service.enable_for_object("items", actor_user_id="operator")["mirror"]["id"]
    if case == "partial_scope":
        service.enable_for_object("orders", actor_user_id="operator")
    with transaction() as session:
        store = service._storage()
        operation, = store.ops(session, mirror_id)
        store.save_op(session, dict(operation, state="applied", publication_receipt={"recorded": True}))
    if case == "superseded_revision":
        service.set_enabled(mirror_id, enabled=False, actor_user_id="operator")
        service.enable_for_object("items", actor_user_id="operator")
    control.reconcile_published_scope(SOURCE)
    with transaction() as session:
        state = control.load_binding(session, SOURCE)
        state.update(owner_epoch=1, runtime_instance_id="agent-one", applied_revision=state["control_revision"])
        stamp = {key: state[key] for key in control.AUTHORITY_KEYS}
        state["allocation"] = dict(command={"operation_id": "owner"}, evidence={"target_fence": dict(
            operation_id="owner", authority=stamp, mirror_receipts={mirror_id: "receipt"},
        )})
        save_binding(session, state)
    authority = service.Authority(**delivery_composition._target_authority(stamp))
    monkeypatch.setattr(service, "_observe_applied_open", lambda *args: pytest.fail("partial scope was observed"))
    with pytest.raises(service.MirrorError, match="MIRROR_CONTROL_CONFLICT"):
        service.current_open_preparations(authority=authority, published_scope=state["published_scope"],
                                          observe_committed=pytest.fail)


@pytest.mark.parametrize("management", ["without_credentials"], indirect=True)
def test_published_intent_does_not_reserve_capture_before_credentials(management, tmp_path):
    service.enable_for_object("items", actor_user_id="operator")
    journal = CommandJournal(tmp_path)
    try:
        runtime = CaptureRuntime(journal=journal, connect=None, signals=None)
        assert runtime.poll_once(SOURCE) == "idle"
        assert control.capture_status(SOURCE)["binding_id"] is None
        assert pending_capture_commands() == ()

        with control.source_control_transaction(SOURCE) as (session, source):
            configured = replace(source, capture_credential_ciphertext="encrypted", capture_revision=1)
            get_source_store().save_source_on(session, configured)
            control.record_source_intent(session, source, configured, actor_user_id=None, actor_token_id=None)
        assert control.capture_status(SOURCE)["binding_id"] is not None
        with pytest.raises(RuntimeBlocked, match="owner_assignment_unproven"):
            runtime.poll_once(SOURCE)
        command, = pending_capture_commands()
        assert command["kind"] == "reconcile"
        assert [row["qualified_table"] for row in command["published_scope"] if row["included"]] == ["public.items"]
    finally:
        journal.close()


def test_independent_mirrors_disable_supersession_and_global_stop(management, tmp_path):
    journal = CommandJournal(tmp_path)
    runtime = CaptureRuntime(journal=journal, connect=None, signals=None)

    def pending():
        with pytest.raises(RuntimeBlocked, match="owner_assignment_unproven"):
            runtime.poll_once(SOURCE)
        command, = pending_capture_commands()
        return command

    try:
        orders = service.enable_for_object("orders", actor_user_id="operator")["mirror"]
        opened = service.enable_for_object("items", actor_user_id="operator")
        initial = pending()
        assert [table["qualified_table"] for table in initial["published_scope"]] == ["public.items", "public.orders"]
        assert service.enable_for_object("items", actor_user_id="operator") == opened
        assert pending() == initial

        mirror_id = opened["mirror"]["id"]
        service.set_enabled(mirror_id, enabled=False, actor_user_id="operator")
        disabled = pending()
        assert disabled["control_revision"] == initial["control_revision"] + 1
        assert [(table["qualified_table"], table["included"], table["mirror_revision"])
                for table in disabled["published_scope"]] == [("public.items", False, 2), ("public.orders", True, 1)]
        mirror = service.get_mirror(mirror_id)
        assert {op["kind"]: op["state"] for op in mirror["operations"]} == {"open": "superseded", "disable": "pending"}
        assert mirror["control"]["stop_ack"] is None
        with control.source_control_transaction(SOURCE) as (session, source):
            stopped = replace(source, status="disabled")
            get_source_store().save_source_on(session, stopped)
            control.record_source_intent(session, source, stopped, actor_user_id=None, actor_token_id=None)
        command = pending()
        assert command["kind"] == "stop"
        assert command["published_scope"] == disabled["published_scope"]
        assert control.capture_status(SOURCE)["control"]["stop_ack"] is None
        assert [op["state"] for op in control.capture_status(SOURCE)["operations"]] == [
            "superseded", "superseded", "superseded", "pending",
        ]
        service.set_enabled(orders["id"], enabled=False, actor_user_id="operator")
        withdrawn = pending()
        assert withdrawn["kind"] == "stop"
        assert withdrawn["control_revision"] == command["control_revision"] + 1
        assert [table["included"] for table in withdrawn["published_scope"]] == [False, False]
    finally:
        journal.close()


def test_rollbacks_leave_older_scope_and_command_current(management, tmp_path):
    old, = pending_capture_commands()

    def fail_open(mapper, connection, operation):
        raise RuntimeError("open rollback")

    event.listen(MirrorOperationRow, "after_insert", fail_open)
    try:
        with pytest.raises(RuntimeError, match="open rollback"):
            service.enable_for_object("items", actor_user_id="operator")
    finally:
        event.remove(MirrorOperationRow, "after_insert", fail_open)
    control.reconcile_published_scope(SOURCE)
    assert pending_capture_commands() == (old,)
    assert inventory()["total"] == 0
    service.enable_for_object("items", actor_user_id="operator")

    def fail_after_insert(mapper, connection, command):
        raise RuntimeError("failed before capture commit")

    journal = CommandJournal(tmp_path)
    runtime = CaptureRuntime(journal=journal, connect=None, signals=None)
    try:
        event.listen(SourceCaptureOperationRow, "after_insert", fail_after_insert)
        try:
            with pytest.raises(RuntimeError, match="failed before capture commit"):
                runtime.poll_once(SOURCE)
        finally:
            event.remove(SourceCaptureOperationRow, "after_insert", fail_after_insert)
        assert pending_capture_commands() == (old,)
        with pytest.raises(RuntimeBlocked, match="owner_assignment_unproven"):
            runtime.poll_once(SOURCE)
        recovered, = pending_capture_commands()
        assert recovered["control_revision"] == old["control_revision"] + 1
        assert recovered["kind"] == "reconcile"
    finally:
        journal.close()


@pytest.mark.parametrize(("stopping", "mismatch"), [
    *[(False, mismatch) for mismatch in (
        None, "connector", "publication", "publication_filter", "publication_columns", "publication_generated",
        "manifest", "target", "anchored_target", "delivery_settings", "scope_superseded", "readiness",
        "gateway_missing", "allocation_stale", "allocation_scope", "allocation_source", "exclusion", "fence",
        "response_loss", "superseded_pending", "revision_restart", "later_owner",
    )],
    *[(True, mismatch) for mismatch in (None, "connector", "delivery_settings", "scope_superseded", "containment")],
])
def test_protected_runtime_entry_requires_all_bindings_before_connect_mutation(
    management, tmp_path, monkeypatch, capsys, mismatch, stopping, request,
):
    # The independent observers and the management intent use the same fixture instant.
    # Invalid freshness scenarios explicitly offset their observation.
    clock = get_clock()
    set_clock(FixedClock(utc_now() - timedelta(seconds=1)))
    request.addfinalizer(lambda: set_clock(clock))
    opened = service.enable_for_object("items", actor_user_id="operator")["mirror"]
    control.reconcile_published_scope(SOURCE)
    if stopping:
        with control.source_control_transaction(SOURCE) as (session, source):
            disabled = replace(source, status="disabled")
            get_source_store().save_source_on(session, disabled)
            control.record_source_intent(session, source, disabled, actor_user_id=None, actor_token_id=None)
    pending, = pending_capture_commands()
    previous = {key: pending[key] for key in control.AUTHORITY_KEYS}
    current = dict(previous, owner_epoch=1, runtime_instance_id="agent-one",
                   control_revision=pending["control_revision"] + 1)
    profile_scope = dict(source_id=SOURCE, connector_name="cap_one", host="pg.internal", port=5432,
                         database="db", tables=["public.orders" if mismatch == "connector"
                                                else "public.items"], publication="capture_pub",
                         slot="capture_slot", topic_prefix="cap", server_version_num=180000)
    target_authority = dict(current, resource_binding_id=current["binding_id"], capture_generation="1")
    del target_authority["binding_id"]
    partition = dict(runtime_cluster_id="cluster", topic_incarnation_id="incarnation", partition=0)
    table = dict(authority=target_authority, generation_id="generation", partition_identity=partition,
                 topic="cap.public.items", schema_fingerprint="fingerprint", native_types={"id": "integer", "body": "text"},
                 decoder=dict(table_identity="orders" if mismatch == "manifest" else "items", capture_generation="1",
                              database="db", namespace="cap", schema_name="public", table_name="items",
                              connector_version="3.4.0.Final", key_schema=KEY, value_schema=SCHEMA))
    metadata = dict(authority=target_authority, generation_id="generation", partition_identity=partition,
                    schema_fingerprint="fingerprint", native_types=table["native_types"], table_identity="items",
                    capture_generation="1", key_columns=["id"], column_names=["id", "body"], cleanup_pending=False,
                    status="building")
    if mismatch == "anchored_target":
        metadata.update(status="published", anchored_profile={"kind": "disposable_read_committed_v1", "leader_epoch": 3})

    def private(name, data):
        path = tmp_path / name
        path.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())
        path.chmod(0o600)
        return str(path)

    def signed(purpose, operation_id, scope, *, authority=current, **claims):
        now = utc_now()
        return jwt.encode(dict(iss="gateway", aud="capture", iat=now, nbf=now, exp=now + timedelta(seconds=60),
                               jti="proof", purpose=purpose, authority=authority, operation_id=operation_id, scope=scope,
                               **claims), SIGNING_KEY, algorithm="EdDSA", headers={"kid": "trusted"})

    signing_key = private("gateway.pem", SIGNING_KEY.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    allocation_scope = dict(profile=profile_scope, published_scope=pending["published_scope"])
    allocation_proof = signed("owner_allocation", "allocated", allocation_scope, previous_authority=previous)
    allocation = private("owner.json", dict(operation_id="allocated", signature=allocation_proof))

    class SourceConnection:
        def __enter__(self):
            return self

        def __exit__(self, *error):
            return None

        def cursor(self):
            return self

        def execute(self, sql, params=None):
            self.sql = sql

        def fetchone(self):
            if "current_database" in self.sql:
                return ("db", "logical", 180000, True, False)
            if "puballtables" in self.sql:
                return (False, True, True, True, True)
            if "pg_replication_slots" in self.sql:
                return None
            return (True,)

        def fetchall(self):
            assert "pg_publication_tables" in self.sql
            return [(
                "public.orders" if mismatch == "publication" else "public.items",
                mismatch == "publication_filter",
                ["id"] if mismatch == "publication_columns" else ["id", "body"],
                ["id", "body"],
                mismatch == "publication_generated",
            )]

    mutations = []
    installed = {}
    allocation_calls = []
    receipts = {}
    containment = {"withhold_stop": mismatch == "containment"}

    class Transport:
        def request(self, method, path, payload=None, **options):
            if path == "/v1/capture/owner-allocations":
                allocation_calls.append(payload)
                command = payload["command"]
                op = command["operation_id"]
                assert payload["authorization"] == allocation_proof
                assert control.capture_status(SOURCE)["control"]["owner_epoch"] == previous["owner_epoch"]
                assert all(command != exposed for exposed in pending_capture_commands())
                if mismatch == "gateway_missing" or (mismatch == "containment" and len(allocation_calls) > 1):
                    raise RuntimeBlocked("private_http_unconfirmed")
                result = allocation_observation(payload)
                if command["kind"] == "stop" or mismatch == "readiness":
                    result["checks"].update(source_pressure="unknown", credential_valid="fail")
                if mismatch == "allocation_stale":
                    result["observed_at"] = (utc_now() - timedelta(minutes=1)).isoformat()
                if mismatch == "allocation_source":
                    result["command"] = dict(command, source_id="other-source")
                if mismatch == "exclusion":
                    result["exclusion"] = {"old_agent_excluded": True, "old_tasks_excluded": True}
                if mismatch == "fence":
                    result["target_fence"]["mirror_receipts"] = {}
                if mismatch in {"response_loss", "superseded_pending"}:
                    if op not in receipts:
                        receipts[op] = result["target_fence"]
                        raise RuntimeBlocked("private_http_uncertain")
                    result["target_fence"] = receipts[op]
                signed_scope = allocation_scope if mismatch != "allocation_scope" else dict(allocation_scope, published_scope=[])
                return {"signature": signed("observation:owner_allocation", op, signed_scope,
                                            authority=current, observation=result)}
            if path == "/v1/capture/observations":
                command = payload["command"]
                assert command["published_scope"][0]["mirror_id"] == opened["id"]
                phase = payload["phase"]
                if containment["withhold_stop"]:
                    raise RuntimeBlocked("private_http_unconfirmed")
                checks = {"source_pressure": "unknown", "credential_valid": "fail"} if phase in {"before_stop", "stopped"} else None
                result = observation(command, phase, checks=checks)
                result.pop("signature")
                return dict(result, signature=signed(f"observation:{phase}", command["operation_id"], profile_scope,
                                                     authority={key: command[key] for key in control.AUTHORITY_KEYS},
                                                     observation=result))
            if method == "PUT":
                mutations.append(path)
                installed[path] = payload
                return None
            if path.endswith("/config"):
                return installed.get(path)
            running = (not any(path.endswith("/stop") for path in mutations)
                       and (stopping or mismatch == "revision_restart"
                            or any(path.endswith("/resume") for path in mutations)))
            state = "RUNNING" if running else "STOPPED"
            return dict(connector=dict(state=state), tasks=[dict(state=state)])

        def close(self):
            return None

    monkeypatch.setattr(entrypoint, "PrivateHTTP", Transport)
    monkeypatch.setattr(entrypoint, "PostgreSQLCaptureProfile", lambda **args: PostgreSQLCaptureProfile(
        **args, connect=lambda **kwargs: SourceConnection(),
    ))
    monkeypatch.setattr(delivery_composition, "applier_engine", lambda settings: SimpleNamespace(dispose=lambda: None))
    monkeypatch.setattr(delivery_composition, "current_open_preparations", lambda **kwargs: ([], []))
    monkeypatch.setattr(delivery_composition, "target_metadata", lambda *args: None if mismatch == "target" else metadata)
    monkeypatch.setattr(delivery_composition, "open_delivery", lambda **args: SimpleNamespace(poll_once=lambda: 0, close=lambda: None))
    settings = dict(target={}, tables=[table], kafka={}, group_id="scope-test", limits={}, max_age_seconds=30)
    entry = dict(source_id=SOURCE, connector_name="cap_one", connect_tls={}, signals_tls={},
                 signing_trust=dict(public_key_files={"trusted": signing_key}, issuer="gateway", audience="capture"),
                 postgresql_profile=dict(scope=profile_scope, tls=dict(sslmode="verify-full", sslrootcert="fixture")),
                 readiness_policy=dict(runtime_instance_id="agent-one", max_age_seconds=30, required_checks=CHECKS),
                 credential_files=dict(directory=str(tmp_path), provider_directory="/private/capture"),
                 delivery_settings_file=private("delivery.json", settings), owner_allocation_file=allocation)

    if mismatch == "delivery_settings":
        entry["delivery_settings_file"] = str(tmp_path / "missing-delivery.json")
    if mismatch == "scope_superseded":
        record_evidence = entrypoint.record_applied_evidence

        def withdraw_before_acceptance(**kwargs):
            service.set_enabled(opened["id"], enabled=False, actor_user_id="operator")
            return record_evidence(**kwargs)

        monkeypatch.setattr(entrypoint, "record_applied_evidence", withdraw_before_acceptance)
    runtime_config = dict(state_directory=str(tmp_path), poll_interval_seconds=1, sources=[entry],
                          management_database_url_file=private("management.url", b"postgresql://fixture/management?sslmode=verify-full"))
    config = private("runtime.json", runtime_config)
    monkeypatch.setattr("sys.argv", ["runtime", "--config-file", config, "--once"])
    if mismatch in {"response_loss", "superseded_pending", "containment"}:
        assert entrypoint.main() == 2
        assert mutations == []
        assert len(allocation_calls) == 1
        if mismatch == "response_loss":
            assert pending_capture_commands() == (pending,)
            competing = dict(current, runtime_instance_id="agent-two")
            private("owner.json", dict(operation_id="competing", signature=signed(
                "owner_allocation", "competing", allocation_scope, authority=competing, previous_authority=previous,
            )))
            entry["readiness_policy"]["runtime_instance_id"] = "agent-two"
            private("runtime.json", runtime_config)
            assert entrypoint.main() == 2
            assert len(allocation_calls) == 1
            assert mutations == []
            entry["readiness_policy"]["runtime_instance_id"] = "agent-one"
            private("runtime.json", runtime_config)
            private("owner.json", dict(operation_id="allocated", signature=allocation_proof))
            commit_allocation = entrypoint.allocate_owner

            def lose_promotion_response(**kwargs):
                commit_allocation(**kwargs)
                raise RuntimeBlocked("promotion_response_lost")

            with monkeypatch.context() as patch:
                patch.setattr(entrypoint, "allocate_owner", lose_promotion_response)
                assert entrypoint.main() == 2
            assert mutations == []
            committed, = pending_capture_commands()
            assert committed["operation_id"] == "allocated"
            assert committed["owner_epoch"] == 1
            assert allocation_calls[0] == allocation_calls[1]
            assert len(receipts) == 1
            assert entrypoint.main() == 0
            assert len(allocation_calls) == 2
            assert mutations == ["/connectors/cap_one/config", "/connectors/cap_one/resume"]
            return
        if mismatch == "superseded_pending":
            service.set_enabled(opened["id"], enabled=False, actor_user_id="operator")
            assert entrypoint.main() == 0
            assert allocation_calls == [allocation_calls[0]] * 2
            assert len(receipts) == 1
            assert mutations == []
            state = control.capture_status(SOURCE)["control"]
            assert state["owner_epoch"] == 1 and state["desired"] == "stopped"
            assert state["applied_revision"] == current["control_revision"] + 1
            assert state["stop_ack"]["operation_id"] != "allocated"
            return
        containment["withhold_stop"] = False
        stop_command, = pending_capture_commands()
        previous = {key: stop_command[key] for key in control.AUTHORITY_KEYS}
        current = dict(previous, owner_epoch=2, control_revision=previous["control_revision"] + 1)
        allocation_proof = signed("owner_allocation", "unavailable", allocation_scope,
                                  authority=current, previous_authority=previous)
        private("owner.json", dict(operation_id="unavailable", signature=allocation_proof))
        assert entrypoint.main() == 2
        assert len(allocation_calls) == 2
        assert mutations == ["/connectors/cap_one/stop"]
        assert control.capture_status(SOURCE)["control"]["stop_ack"]["operation_id"] == "allocated"
        return
    if mismatch == "revision_restart":
        assert entrypoint.main() == 0
        service.set_enabled(opened["id"], enabled=False, actor_user_id="operator")
        assert entrypoint.main() == 0
        assert len(allocation_calls) == 1
        assert mutations == ["/connectors/cap_one/config", "/connectors/cap_one/stop"]
        status = control.capture_status(SOURCE)["control"]
        assert status["owner_epoch"] == 1
        assert status["stop_ack"]["operation_id"] != "allocated"
        return
    if mismatch == "later_owner":
        assert entrypoint.main() == 0
        first_proof = allocation_proof
        baseline_mutations = list(mutations)
        with control.source_control_transaction(SOURCE) as (session, source):
            disabled = replace(source, status="disabled")
            get_source_store().save_source_on(session, disabled)
            control.record_source_intent(session, source, disabled, actor_user_id=None, actor_token_id=None)
        stop_command, = pending_capture_commands()
        previous = {key: stop_command[key] for key in control.AUTHORITY_KEYS}
        current = dict(previous, owner_epoch=2, runtime_instance_id="agent-two",
                       control_revision=previous["control_revision"] + 1)
        allocation_proof = signed("owner_allocation", "takeover", allocation_scope,
                                  authority=current, previous_authority=previous)
        private("owner.json", dict(operation_id="takeover", signature=allocation_proof))
        entry["readiness_policy"]["runtime_instance_id"] = "agent-two"
        private("runtime.json", runtime_config)
        containment["withhold_stop"] = True
        assert entrypoint.main() == 2
        assert control.capture_status(SOURCE)["control"]["owner_epoch"] == 2
        containment["withhold_stop"] = False
        private("owner.json", dict(operation_id="allocated", signature=first_proof))
        entry["readiness_policy"]["runtime_instance_id"] = "agent-one"
        private("runtime.json", runtime_config)
        assert entrypoint.main() == 2
        assert mutations == baseline_mutations
        assert control.capture_status(SOURCE)["control"]["stop_ack"] is None
        private("owner.json", dict(operation_id="takeover", signature=allocation_proof))
        entry["readiness_policy"]["runtime_instance_id"] = "agent-two"
        private("runtime.json", runtime_config)
        assert entrypoint.main() == 0
        assert len(allocation_calls) == 2
        assert mutations == [*baseline_mutations, "/connectors/cap_one/stop"]
        assert control.capture_status(SOURCE)["control"]["stop_ack"]["operation_id"] == "takeover"
        return
    assert entrypoint.main() == (2 if mismatch and not stopping else 0)
    if stopping:
        assert mutations == ["/connectors/cap_one/stop"]
        status = control.capture_status(SOURCE)["control"]
        assert status["applied_revision"] == current["control_revision"]
        assert status["stop_ack"]["operation_id"] == "allocated"
    elif mismatch == "scope_superseded":
        assert mutations == ["/connectors/cap_one/config", "/connectors/cap_one/resume"]
        assert control.capture_status(SOURCE)["control"]["applied_revision"] is None
        assert json.loads(capsys.readouterr().out) == dict(source_id=SOURCE, state="blocked", code="capture_evidence_rejected")
        control.reconcile_published_scope(SOURCE)
        command, = pending_capture_commands()
        assert command["kind"] == "stop"
    elif mismatch:
        assert mutations == []
        assert control.capture_status(SOURCE)["control"]["applied_revision"] is None
        if mismatch in {"readiness", "gateway_missing", "allocation_stale", "allocation_scope", "allocation_source", "exclusion", "fence"}:
            assert control.capture_status(SOURCE)["control"]["owner_epoch"] == 0
    else:
        assert mutations == ["/connectors/cap_one/config", "/connectors/cap_one/resume"]
        assert installed[mutations[0]]["table.include.list"] == r"public\.items"
        assert control.capture_status(SOURCE)["control"]["applied_revision"] == 3
        assert service.get_mirror(opened["id"])["published_generation_id"] is None
