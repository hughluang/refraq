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
from backend.core.time import utc_now
from backend.metadata.capture import control, delivery_composition, runtime as entrypoint
from backend.metadata.capture.postgresql import PostgreSQLCaptureProfile
from backend.metadata.capture.runtime import CaptureRuntime
from backend.metadata.capture.runtime_store import CommandJournal, RuntimeBlocked
from backend.metadata.capture.test_delivery import KEY, SCHEMA
from backend.metadata.capture.test_runtime import CHECKS, SIGNING_KEY, observation
from backend.metadata.mirrors import service
from backend.metadata.mirrors.models import (
    MirrorIntentReceiptRow, MirrorOperationRow, MirrorPublicationRow, MirrorReferenceRow, MirrorRow,
)
from backend.metadata.mirrors.store import SqlMirrorStore
from backend.metadata.models import CatalogObjectRow, SourceCaptureBindingRow, SourceCaptureOperationRow, SourceRow
from backend.metadata.sources.store import SourceRecord, get_source_store, reset_source_store


SOURCE = "source-one"


@pytest.fixture
def management(monkeypatch, tmp_path, request):
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "persistent")
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "offline-scope-fixture")
    get_settings.cache_clear()
    reset_source_store()
    engine = create_engine(f"sqlite:///{tmp_path / 'management.sqlite3'}")
    for model in (SourceRow, CatalogObjectRow, SourceCaptureBindingRow, SourceCaptureOperationRow, MirrorRow,
                  MirrorReferenceRow, MirrorOperationRow, MirrorPublicationRow, MirrorIntentReceiptRow,
                  service.HistoryGateRow):
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
    service.bind_management(store=Store())
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
    try:
        yield transaction, source
    finally:
        service.bind_management()
        engine.dispose()
        reset_source_store()
        get_settings.cache_clear()


def publish(session, channel, version, objects, *, confirmed=None):
    if confirmed is None:
        confirmed = [
            {key: binding[key] for key in ("source_id", "object_id", "mirror_id")}
            for binding in service.resolve_object_bindings(object_ids=objects, session=session)
            if binding["needs_open"]
        ]
    return service.ensure_open_intent(
        session, operation_id=f"{channel}:{version}", channel_id=channel,
        channel_version=version, object_ids=objects, confirmed_mirrors_to_open=confirmed,
    )


def test_committed_confirmed_open_becomes_current_capture_command(management, tmp_path):
    transaction, _ = management
    with transaction() as session:
        orders, = publish(session, "workflow", 1, ["orders"])
    journal = CommandJournal(tmp_path)
    runtime = CaptureRuntime(journal=journal, connect=None, signals=None)
    try:
        with pytest.raises(RuntimeBlocked, match="owner_assignment_unproven"):
            runtime.poll_once(SOURCE)
        command, = control.pending_commands(SOURCE)
        assert command["kind"] == "reconcile"
        assert command["control_revision"] == 2
        assert command["published_scope"] == [{
            "mirror_id": orders["mirror_id"], "table_identity": "orders",
            "qualified_table": "public.orders", "mirror_revision": 1, "included": True,
        }]
        mirror = service.get_mirror(orders["mirror_id"])
        assert mirror["operations"][0]["state"] == "pending"
        assert mirror["published_generation_id"] is None
    finally:
        journal.close()


@pytest.mark.parametrize("management", ["without_credentials"], indirect=True)
def test_published_intent_does_not_reserve_capture_before_credentials(management, tmp_path):
    transaction, _ = management
    with transaction() as session:
        publish(session, "workflow", 1, ["items"])
    journal = CommandJournal(tmp_path)
    try:
        runtime = CaptureRuntime(journal=journal, connect=None, signals=None)
        assert runtime.poll_once(SOURCE) == "idle"
        assert control.capture_status(SOURCE)["binding_id"] is None
        assert control.pending_commands(SOURCE) == ()

        with control.source_control_transaction(SOURCE) as (session, source):
            configured = replace(source, capture_credential_ciphertext="encrypted", capture_revision=1)
            get_source_store().save_source_on(session, configured)
            control.record_source_intent(session, source, configured, actor_user_id=None, actor_token_id=None)
        assert control.capture_status(SOURCE)["binding_id"] is not None
        with pytest.raises(RuntimeBlocked, match="owner_assignment_unproven"):
            runtime.poll_once(SOURCE)
        command, = control.pending_commands(SOURCE)
        assert command["kind"] == "reconcile"
        assert [row["qualified_table"] for row in command["published_scope"] if row["included"]] == ["public.items"]
    finally:
        journal.close()


def test_shared_references_disable_supersession_and_global_stop(management, tmp_path):
    transaction, _ = management
    journal = CommandJournal(tmp_path)
    runtime = CaptureRuntime(journal=journal, connect=None, signals=None)

    def pending():
        with pytest.raises(RuntimeBlocked, match="owner_assignment_unproven"):
            runtime.poll_once(SOURCE)
        command, = control.pending_commands(SOURCE)
        return command

    try:
        with transaction() as session:
            publish(session, "first", 1, ["orders", "items"])
            duplicate, = publish(session, "second", 1, ["items"])
        initial = pending()
        assert [table["qualified_table"] for table in initial["published_scope"]] == ["public.items", "public.orders"]
        with transaction() as session:
            publish(session, "first", 2, ["orders"])
        assert pending() == initial
        with transaction() as session:
            assert publish(session, "second", 1, ["items"]) == [duplicate]
        assert pending() == initial

        mirror_id = duplicate["mirror_id"]
        service.set_enabled(mirror_id, enabled=False, actor_user_id="operator")
        disabled = pending()
        assert disabled["control_revision"] == initial["control_revision"] + 1
        assert [(table["qualified_table"], table["included"], table["mirror_revision"])
                for table in disabled["published_scope"]] == [("public.items", False, 2), ("public.orders", True, 1)]
        mirror = service.get_mirror(mirror_id)
        assert {op["kind"]: op["state"] for op in mirror["operations"]} == {"open": "superseded", "disable": "pending"}
        assert mirror["control"]["stop_ack"] is None
        with transaction() as session:
            assert publish(session, "second", 1, ["items"], confirmed=[]) == [duplicate]
        assert pending() == disabled

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
        with transaction() as session:
            service.reconcile_references(session, channel_id="first", channel_version=3, object_ids=[])
        withdrawn = pending()
        assert withdrawn["kind"] == "stop"
        assert withdrawn["control_revision"] == command["control_revision"] + 1
        assert [table["included"] for table in withdrawn["published_scope"]] == [False, False]
    finally:
        journal.close()


def test_rollbacks_leave_older_scope_and_command_current(management, tmp_path):
    transaction, _ = management
    old, = control.pending_commands(SOURCE)
    with pytest.raises(RuntimeError, match="publish rollback"), transaction() as session:
        publish(session, "workflow", 1, ["items"])
        raise RuntimeError("publish rollback")
    control.reconcile_published_scope(SOURCE)
    assert control.pending_commands(SOURCE) == (old,)
    assert service.list_mirrors()["total"] == 0

    with transaction() as session:
        publish(session, "workflow", 1, ["items"])

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
        assert control.pending_commands(SOURCE) == (old,)
        with pytest.raises(RuntimeBlocked, match="owner_assignment_unproven"):
            runtime.poll_once(SOURCE)
        recovered, = control.pending_commands(SOURCE)
        assert recovered["control_revision"] == old["control_revision"] + 1
        assert recovered["kind"] == "reconcile"
    finally:
        journal.close()


@pytest.mark.parametrize(("stopping", "mismatch"), [
    *[(False, mismatch) for mismatch in (
        None, "connector", "publication", "publication_filter", "publication_columns", "publication_generated",
        "manifest", "target", "delivery_settings", "scope_superseded",
    )],
    *[(True, mismatch) for mismatch in (None, "connector", "delivery_settings", "scope_superseded")],
])
def test_protected_runtime_entry_requires_all_bindings_before_connect_mutation(
    management, tmp_path, monkeypatch, capsys, mismatch, stopping,
):
    transaction, _ = management
    with transaction() as session:
        opened, = publish(session, "workflow", 1, ["items"])
    control.reconcile_published_scope(SOURCE)
    if stopping:
        with control.source_control_transaction(SOURCE) as (session, source):
            disabled = replace(source, status="disabled")
            get_source_store().save_source_on(session, disabled)
            control.record_source_intent(session, source, disabled, actor_user_id=None, actor_token_id=None)
    pending, = control.pending_commands(SOURCE)
    previous = {key: pending[key] for key in control.AUTHORITY_KEYS}
    current = dict(previous, owner_epoch=1, runtime_instance_id="agent-one",
                   control_revision=pending["control_revision"] + 1)
    profile_scope = dict(source_id=SOURCE, connector_name="cap_one", host="pg.internal", port=5432,
                         database="db", tables=["public.orders" if stopping and mismatch == "connector"
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

    def private(name, data):
        path = tmp_path / name
        path.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())
        path.chmod(0o600)
        return str(path)

    def signed(purpose, operation_id, scope, **claims):
        now = utc_now()
        return jwt.encode(dict(iss="gateway", aud="capture", iat=now, nbf=now, exp=now + timedelta(seconds=60),
                               jti="proof", purpose=purpose, authority=current, operation_id=operation_id, scope=scope,
                               **claims), SIGNING_KEY, algorithm="EdDSA", headers={"kid": "trusted"})

    signing_key = private("gateway.pem", SIGNING_KEY.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    allocation_proof = signed(
        "owner_allocation", "allocated", profile_scope, previous_authority=previous,
        facts=dict(old_agent_excluded=True, old_tasks_excluded=True, target_fence_installed=True),
    )
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

    class Transport:
        def request(self, method, path, payload=None, **options):
            if path == "/v1/capture/observations":
                command = payload["command"]
                assert command["published_scope"][0]["mirror_id"] == opened["mirror_id"]
                phase = payload["phase"]
                checks = {"source_pressure": "unknown", "credential_valid": "fail"} if stopping else None
                result = observation(command, phase, checks=checks)
                result.pop("signature")
                return dict(result, signature=signed(f"observation:{phase}", command["operation_id"], profile_scope,
                                                     observation=result))
            if method == "PUT":
                mutations.append(path)
                installed[path] = payload
                return None
            if path.endswith("/config"):
                return installed.get(path)
            running = (not any(path.endswith("/stop") for path in mutations) if stopping
                       else any(path.endswith("/resume") for path in mutations))
            state = "RUNNING" if running else "STOPPED"
            return dict(connector=dict(state=state), tasks=[dict(state=state)])

        def close(self):
            return None

    monkeypatch.setattr(entrypoint, "PrivateHTTP", Transport)
    monkeypatch.setattr(entrypoint, "PostgreSQLCaptureProfile", lambda **args: PostgreSQLCaptureProfile(
        **args, connect=lambda **kwargs: SourceConnection(),
    ))
    monkeypatch.setattr(delivery_composition, "applier_engine", lambda settings: SimpleNamespace(dispose=lambda: None))
    monkeypatch.setattr(delivery_composition, "target_metadata", lambda *args: None if mismatch == "target" else metadata)
    monkeypatch.setattr(delivery_composition, "open_delivery", lambda **args: SimpleNamespace(poll_once=lambda: 0, close=lambda: None))
    monkeypatch.setenv("DATABASE_URL", "postgresql://fixture/management?sslmode=verify-full")
    settings = dict(target={}, tables=[table], kafka={}, group_id="scope-test", limits={}, max_age_seconds=30)
    entry = dict(source_id=SOURCE, connector_name="cap_one", connect_tls={}, signals_tls={},
                 signing_trust=dict(public_key_files={"trusted": signing_key}, issuer="gateway", audience="capture"),
                 postgresql_profile=dict(scope=profile_scope, tls=dict(sslmode="verify-full", sslrootcert="fixture")),
                 readiness_policy=dict(runtime_instance_id="agent-one", max_age_seconds=30, required_checks=CHECKS),
                 credential_files=dict(directory=str(tmp_path), provider_directory="/private/capture"),
                 delivery_settings_file=private("delivery.json", settings), owner_allocation_file=allocation)

    if mismatch == "delivery_settings":
        entry["delivery_settings_file"] = str(tmp_path / "missing-delivery.json")
    if mismatch == "connector" and not stopping:
        assert control.allocate_owner(
            source_id=SOURCE, runtime_instance_id="agent-one", operation_id="allocated",
            signed_proof=allocation_proof,
            verifier=entrypoint.SignedAuthority(keys={"trusted": SIGNING_KEY.public_key()}, issuer="gateway", audience="capture"),
            scope=profile_scope,
        )["control_revision"] == 3
        entry["postgresql_profile"]["scope"] = dict(profile_scope, tables=["public.orders"])
    if mismatch == "scope_superseded":
        record_evidence = entrypoint.record_applied_evidence

        def withdraw_before_acceptance(**kwargs):
            with transaction() as session:
                service.reconcile_references(session, channel_id="workflow", channel_version=2, object_ids=[])
            return record_evidence(**kwargs)

        monkeypatch.setattr(entrypoint, "record_applied_evidence", withdraw_before_acceptance)
    config = private("runtime.json", dict(state_directory=str(tmp_path), poll_interval_seconds=1, sources=[entry],
                                         management_database_url_file=private("management.url", b"postgresql://fixture/management?sslmode=verify-full")))
    monkeypatch.setattr("sys.argv", ["runtime", "--config-file", config, "--once"])
    assert entrypoint.main() == (2 if mismatch and not stopping else 0)
    if stopping:
        assert mutations == ["/connectors/cap_one/stop"]
        status = control.capture_status(SOURCE)["control"]
        assert status["applied_revision"] == current["control_revision"]
        assert status["stop_ack"]["operation_id"] == "allocated"
    elif mismatch == "scope_superseded":
        assert mutations == ["/connectors/cap_one/config", "/connectors/cap_one/resume"]
        assert control.capture_status(SOURCE)["control"]["applied_revision"] is None
        assert capsys.readouterr().out == ""
        control.reconcile_published_scope(SOURCE)
        command, = control.pending_commands(SOURCE)
        assert command["kind"] == "stop"
    elif mismatch:
        assert mutations == []
        assert control.capture_status(SOURCE)["control"]["applied_revision"] is None
    else:
        assert mutations == ["/connectors/cap_one/config", "/connectors/cap_one/resume"]
        assert installed[mutations[0]]["table.include.list"] == r"public\.items"
        assert control.capture_status(SOURCE)["control"]["applied_revision"] == 3
        assert service.get_mirror(opened["mirror_id"])["published_generation_id"] is None
