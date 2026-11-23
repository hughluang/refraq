"""Offline signed-authority and Connect start boundary tests."""

from datetime import timedelta
import json

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backend.core.config import get_settings
from backend.core.time import utc_now
from backend.core.secrets import encrypt_secret
from backend.metadata.capture.authority import SignedAuthority
from backend.metadata.capture.control import AUTHORITY_KEYS, allocate_owner, capture_status, reconcile_published_scope
from backend.metadata.capture.credentials import CredentialFiles
from backend.metadata.capture.postgresql import PostgreSQLCaptureProfile
from backend.metadata.capture.runtime import CaptureRuntime
from backend.metadata.capture.runtime_adapters import ConnectLifecycle, ReadinessSignals
from backend.metadata.capture.runtime_store import CommandJournal, RuntimeBlocked
from backend.metadata.capture.test_runtime import (
    CHECKS, TRUST, FakeHTTP, allocation_observation, managed_command as managed_command, observation,
)
from backend.metadata.errors import SourceCaptureControlConflict
from backend.metadata.mirrors import service as mirrors
from backend.metadata.mirrors.store import MemoryMirrorStore
from backend.metadata.sources.store import get_source_store


def token(key, *, authority, scope, purpose="owner_allocation", operation_id="cop_new", **extra):
    now = utc_now()
    return jwt.encode({
        "iss": "allocator", "aud": "capture", "iat": now,
        "nbf": now, "exp": now + timedelta(seconds=60), "jti": "proof-one",
        "purpose": purpose, "authority": authority, "scope": scope,
        "operation_id": operation_id, **extra,
    }, key, algorithm="EdDSA", headers={"kid": "trusted"})


def verifier(key):
    return SignedAuthority(keys={"trusted": key.public_key()}, issuer="allocator", audience="capture")


def test_signed_authority_rejects_wrong_key_scope_expiry_and_task():
    key = Ed25519PrivateKey.generate()
    trust = verifier(key)
    authority = {"source_id": "source-one"}
    scope = {"connector_name": "cap_one"}
    proof = token(key, authority=authority, scope=scope)
    assert trust.verify(proof, purpose="owner_allocation", authority=authority,
                        scope=scope, operation_id="cop_new")["jti"] == "proof-one"
    for candidate, expected_scope, operation in (
        (token(Ed25519PrivateKey.generate(), authority=authority, scope=scope), scope, "cop_new"),
        (proof, {"connector_name": "other"}, "cop_new"),
        (proof, scope, "cop_other"),
        (token(key, authority=authority, scope=scope, exp=utc_now() - timedelta(seconds=1)), scope, "cop_new"),
    ):
        with pytest.raises(RuntimeBlocked):
            trust.verify(candidate, purpose="owner_allocation", authority=authority,
                         scope=expected_scope, operation_id=operation)


def test_owner_allocation_uses_current_previous_term_and_emits_real_intent(managed_command):
    store = get_source_store()
    state = store.capture_bindings[managed_command["source_id"]]
    store.get_source(managed_command["source_id"]).capture_revision = state["credential_revision"]
    previous = {key: state[key] for key in AUTHORITY_KEYS}
    authority = {**previous, "owner_epoch": 2, "runtime_instance_id": "agent-two", "control_revision": 3}
    key = Ed25519PrivateKey.generate()
    profile = {"connector_name": "cap_one"}
    scope = {"profile": profile, "published_scope": []}
    proof = token(key, authority=authority, scope=scope, previous_authority=previous)
    observations = []

    def handler(request):
        assert request.url.path == "/v1/capture/owner-allocations"
        payload = json.loads(request.content)
        observations.append(payload)
        result = allocation_observation(payload)
        result["checks"] = {"source_pressure": "unknown"}
        return httpx.Response(200, json={"signature": token(
            key, authority=authority, scope=scope, purpose="observation:owner_allocation", observation=result,
        )})

    http = FakeHTTP(handler)
    signals = ReadinessSignals(http, verifier=verifier(key), runtime_instance_id="agent-two",
                               max_age_seconds=30, required_checks=CHECKS, scope=profile)
    request = dict(source_id=state["source_id"], operation_id="cop_new", signed_proof=proof, signals=signals)
    try:
        cmd = allocate_owner(**request)
        assert cmd["owner_epoch"] == 2
        assert store.capture_operations["cop_new"]["command"] == cmd
        assert "allocation" not in capture_status(state["source_id"])["control"]
        assert allocate_owner(**request) == cmd
        assert len(observations) == 1
        for altered in (dict(operation_id="cop_replay"), dict(signed_proof=proof + "other")):
            with pytest.raises((RuntimeBlocked, SourceCaptureControlConflict)):
                allocate_owner(**(request | altered))
    finally:
        http.client.close()


@pytest.mark.parametrize("slot_from_previous_owner", [True, False])
def test_takeover_during_deferred_enrollment_requires_full_fence_and_releases_old_slot(managed_command, slot_from_previous_owner):
    source_id = managed_command["source_id"]
    sources = get_source_store()
    source = sources.get_source(source_id)
    source.status = "active"
    source.capture_credential_ciphertext = "fixture"
    source.capture_revision = managed_command["credential_revision"]
    registry = mirrors._storage()
    for name in ("orders", "items"):
        registry.bindings[name] = dict(source_id=source_id, source_name="One", source_key="one", object_id=name,
                                       table_identity=name, qualified_table=f"public.{name}")
        opened = mirrors.enable_for_object(name, actor_user_id="operator")
        if name == "orders":
            installed = mirrors.read_published_scope(None, source_id)
            first = opened["operation_id"]
    full_scope = mirrors.read_published_scope(None, source_id)
    state = sources.capture_bindings[source_id]
    previous = {key: state[key] for key in AUTHORITY_KEYS}
    stamp = dict(previous, capture_generation=str(previous["capture_generation"]))
    stamp["resource_binding_id"] = stamp.pop("binding_id")
    generation = "generation-one"
    binding = dict(authority=stamp, generation_id=generation, allocation_operation_id=first,
                   mirror_id=installed[0]["mirror_id"])
    slot = generation if slot_from_previous_owner else "older-generation"
    snapshots = {generation: dict(binding=binding, state="submission_uncertain" if slot_from_previous_owner else "catching_up")}
    if not slot_from_previous_owner:
        snapshots[slot] = dict(binding=dict(binding, generation_id=slot, authority=dict(stamp, control_revision=1)), state="blocked")
    registry.operations[first]["allocation"] = dict(observed=True, mirror_revision=1, generation_id=generation,
                                                    binding=dict(authority=stamp))
    state.update(desired="configured", published_scope=installed, applied_revision=previous["control_revision"],
                 incremental_snapshots=dict(active=slot, generations=snapshots))
    reconcile_published_scope(source_id)
    assert sources.capture_bindings[source_id]["published_scope"] == installed

    key = Ed25519PrivateKey.generate()
    authority = dict(previous, owner_epoch=previous["owner_epoch"] + 1, runtime_instance_id="agent-two",
                     control_revision=previous["control_revision"] + 1)
    profile = {"tables": ["public.orders", "public.items"]}
    scope = dict(profile=profile, published_scope=full_scope)
    observed_commands = []

    def handler(request):
        payload = json.loads(request.content)
        result = allocation_observation(payload)
        observed_commands.append(payload["command"])
        if len(observed_commands) == 1:
            result["target_fence"]["mirror_receipts"].pop(next(row["mirror_id"] for row in full_scope
                                                               if row["table_identity"] == "items"))
        return httpx.Response(200, json={"signature": token(key, purpose="observation:owner_allocation",
                              authority=authority, scope=scope, observation=result)})

    http = FakeHTTP(handler)
    signals = ReadinessSignals(http, verifier=verifier(key), runtime_instance_id="agent-two",
                               max_age_seconds=30, required_checks=CHECKS, scope=profile)
    request = dict(source_id=source_id, operation_id="cop_new", signals=signals)
    proof = token(key, authority=authority, scope=scope, previous_authority=previous)
    try:
        with pytest.raises(RuntimeBlocked, match="signed_authority_unverified"):
            allocate_owner(**request, signed_proof=token(key, authority=authority,
                           scope=dict(profile=profile, published_scope=installed), previous_authority=previous))
        with pytest.raises(RuntimeBlocked, match="allocation_target_fence_unproven"):
            allocate_owner(**request, signed_proof=proof)
        unpromoted = sources.capture_bindings[source_id]
        assert unpromoted["published_scope"] == installed
        assert unpromoted["incremental_snapshots"]["active"] == slot
        command = allocate_owner(**request, signed_proof=proof)
        assert command["published_scope"] == full_scope
        assert observed_commands == [command, command]
        assert allocate_owner(**request, signed_proof=proof) == command
        reconcile_published_scope(source_id)
        promoted = sources.capture_bindings[source_id]
        assert promoted["control_revision"] == authority["control_revision"]
        assert promoted["published_scope"] == full_scope
        assert promoted["incremental_snapshots"] == dict(active=None if slot_from_previous_owner else slot, generations=snapshots)
    finally:
        http.client.close()


def test_credential_files_rotate_revoke_and_refuse_stale_revision(tmp_path, managed_command, monkeypatch):
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "offline-test-only")
    get_settings.cache_clear()
    source = get_source_store().get_source(managed_command["source_id"])
    source.capture_revision = 1
    source.capture_credential_ciphertext = encrypt_secret(json.dumps({"username": "u", "password": "s\necret"}))
    files = CredentialFiles(tmp_path, provider_directory="/private/capture")
    refs = files.install(managed_command, source)
    assert refs["password"].startswith("${file:/private/capture/")
    assert "s\necret" not in repr(refs)
    source.capture_revision = 2
    with pytest.raises(RuntimeBlocked, match="credential_revision"):
        files.install(managed_command, source)
    files.install({**managed_command, "credential_revision": 2}, source)
    assert len(list(tmp_path.glob("*.properties"))) == 1
    files.revoke(managed_command)
    assert list(tmp_path.glob("*.properties")) == []
    get_settings.cache_clear()


def test_connect_create_response_loss_reconciles_without_repeating_mutation(tmp_path, managed_command, monkeypatch):
    cmd = managed_command
    cmd["kind"] = "reconcile"
    store = get_source_store()
    source = store.get_source(cmd["source_id"])
    source.status = "active"
    source.capture_credential_ciphertext = "fixture"
    source.capture_revision = cmd["credential_revision"]
    mirror_store = MemoryMirrorStore()
    mirror_store.bindings["orders"] = dict(
        source_id=source.id, object_id="orders", source_key="one", source_name="One",
        qualified_table="public.orders", table_identity="orders",
    )
    monkeypatch.setattr(mirrors, "_store", mirror_store)
    monkeypatch.setattr(mirrors, "persist_audit_event", lambda **kwargs: None)
    mirrors.enable_for_object("orders", actor_user_id="operator")
    scope = mirrors.read_published_scope(None, source.id)
    cmd["published_scope"] = scope
    store.capture_operations[cmd["operation_id"]]["command"] = cmd
    store.capture_bindings[cmd["source_id"]].update(desired="configured", published_scope=scope)
    config = {"connector.class": "approved", "database.password": "${file:/private/rev:password}"}
    external = {"config": None, "mutations": 0}

    def handler(request):
        if request.url.path == "/v1/capture/observations":
            payload = json.loads(request.content)
            return httpx.Response(200, json=observation(payload["command"], payload["phase"]))
        if request.method == "PUT":
            external["mutations"] += 1
            external["config"] = json.loads(request.content)
            raise RuntimeBlocked("private_http_uncertain")
        if request.url.path.endswith("/config"):
            return httpx.Response(200, json=external["config"])
        return httpx.Response(200, json={"connector": {"state": "RUNNING"},
                                       "tasks": [{"id": 0, "state": "RUNNING"}]})

    class Files:
        def install(self, command, source):
            return {}

    class Profile:
        scope = {"tables": ["public.orders"]}

        def configuration(self, command, source, refs):
            return config

    class Delivery:
        def validate_installation(self, command, *, session):
            return None

    http = FakeHTTP(handler)
    journal = CommandJournal(tmp_path)
    runtime = CaptureRuntime(journal=journal, connect=ConnectLifecycle(http, "cap_one"),
                             signals=ReadinessSignals(http, verifier=TRUST, runtime_instance_id="agent-one",
                                                      max_age_seconds=30, required_checks=CHECKS),
                             credentials=Files(), profile=Profile(), delivery=Delivery())
    with pytest.raises(RuntimeBlocked, match="private_http_uncertain"):
        runtime.poll_source(cmd["source_id"])
    assert external["mutations"] == 1
    # Simulate restart using the persistent journal, not an in-memory phase.
    journal.close()
    runtime.journal = CommandJournal(tmp_path)
    assert runtime.poll_source(cmd["source_id"]) == "applied"
    assert external["mutations"] == 1
    assert capture_status(cmd["source_id"])["control"]["applied_revision"] == cmd["control_revision"]
    runtime.journal.close()
    http.client.close()


@pytest.mark.parametrize(("wal", "transactions"), [("logical", False), ("replica", False), ("logical", True)])
def test_postgresql_profile_inspects_capture_identity_before_config(managed_command, monkeypatch, wal, transactions):
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "offline-test-only")
    get_settings.cache_clear()
    source = get_source_store().get_source(managed_command["source_id"])
    source.access_ciphertext = encrypt_secret(json.dumps({"host": "pg.internal", "port": 5432, "database": "app", "schema": "public"}))
    source.capture_credential_ciphertext = encrypt_secret(json.dumps({"username": "capture", "password": "private"}))
    managed_command["published_scope"] = [
        {"qualified_table": "public.orders", "included": True},
        {"qualified_table": "public.items", "included": False},
        {"qualified_table": "public.unqualified", "included": True},
    ]
    scope = {"source_id": source.id, "connector_name": "cap_one", "host": "pg.internal",
             "port": 5432, "database": "app", "tables": ["public.orders", "public.items"],
             "publication": "capture_pub", "slot": "capture_slot", "topic_prefix": "cap_one",
             "server_version_num": 180000}
    if transactions:
        scope.update(server_version_num=180006, transaction_metadata=True, snapshot={
            "signal_table": "public.signal", "signal_relation_identity": "15:16",
            "notification_topic": "cap_one.notifications", "notification_partition": {"partition": 0},
        })

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def cursor(self):
            return self

        def execute(self, sql, parameters=None):
            self.sql = sql

        def fetchone(self):
            if "pg_constraint" in self.sql:
                return ("15:16", True, True, ["id", "type", "data"], True, True)
            if "current_database" in self.sql:
                return ("app", wal, scope["server_version_num"], True, False)
            if "pg_publication WHERE" in self.sql:
                return (False, True, True, True, True)
            if "pg_replication_slots" in self.sql:
                return ("pgoutput", "app", False)
            return (True,)

        def fetchall(self):
            tables = [(name, False, ["body", "id"], ["id", "body"], False) for name in scope["tables"]]
            if transactions:
                tables.append(("public.signal", False, ["id", "type", "data"], ["data", "id", "type"], False))
            return tables

    def connect(**kwargs):
        assert kwargs["user"] == "capture"
        assert kwargs["sslmode"] == "verify-full"
        return Connection()

    profile = PostgreSQLCaptureProfile(scope=scope, tls={"sslmode": "verify-full", "sslrootcert": "/private/ca"},
                                       connect=connect)
    if wal != "logical":
        with pytest.raises(RuntimeBlocked, match="postgresql_readiness_unconfirmed"):
            profile.configuration(managed_command, source, {"username": "user-ref", "password": "password-ref"})
    else:
        config = profile.configuration(managed_command, source, {"username": "user-ref", "password": "password-ref"})
        assert config["snapshot.mode"] == "no_data"
        expected = r"public\.orders,public\.signal" if transactions else r"public\.orders"
        assert config["table.include.list"] == expected
        assert config["publication.autocreate.mode"] == "disabled"
        assert config.get("provide.transaction.metadata") == ("true" if transactions else None)
        assert "private" not in config.values()
    get_settings.cache_clear()


@pytest.fixture
def scanning_source(managed_command):
    source_id = managed_command["source_id"]
    sources = get_source_store()
    source = sources.get_source(source_id)
    source.status = "active"
    source.capture_credential_ciphertext = "fixture"
    source.capture_revision = managed_command["credential_revision"]
    registry = mirrors._storage()
    for name in ("orders", "items"):
        registry.bindings[name] = dict(source_id=source_id, source_name="One", source_key="one", object_id=name,
                                       table_identity=name, qualified_table=f"public.{name}")
    opened = mirrors.enable_for_object("orders", actor_user_id="operator")
    state = sources.capture_bindings[source_id]
    authority = {key: state[key] for key in AUTHORITY_KEYS}
    stamp = dict(authority, capture_generation=str(authority["capture_generation"]))
    stamp["resource_binding_id"] = stamp.pop("binding_id")
    registry.operations[opened["operation_id"]]["allocation"] = dict(
        observed=True, mirror_revision=1, generation_id="scanning", binding=dict(authority=stamp))
    state.update(desired="configured", published_scope=mirrors.read_published_scope(None, source_id),
                 applied_revision=authority["control_revision"], incremental_snapshots=dict(
                     active="scanning", generations={"scanning": dict(state="snapshotting", binding=dict(
                         authority=stamp, generation_id="scanning", mirror_id=opened["mirror"]["id"],
                         allocation_operation_id=opened["operation_id"]))}))
    return source_id, registry, authority


def test_withdrawing_an_undispatched_sibling_preserves_the_active_copy(scanning_source):
    source_id, registry, authority = scanning_source
    sibling = mirrors.enable_for_object("items", actor_user_id="operator")
    mirrors.set_enabled(sibling["mirror"]["id"], enabled=False, actor_user_id="operator")
    reconcile_published_scope(source_id)
    state = get_source_store().capture_bindings[source_id]
    assert {key: state[key] for key in AUTHORITY_KEYS} == authority
    assert state["incremental_snapshots"]["active"] == "scanning"
    assert [entry["qualified_table"] for entry in state["published_scope"]] == ["public.orders"]
    assert registry.ops(registry, sibling["mirror"]["id"])[-1]["state"] == "pending"


@pytest.mark.parametrize("change", ["enroll", "withdraw"])
def test_exact_takeover_retry_survives_registry_drift_after_a_lost_reply(scanning_source, change):
    exercise_takeover_retry(scanning_source, change, allocation_observation)


def exercise_takeover_retry(scanning_source, change, observe_fence):
    source_id, registry, previous = scanning_source
    if change == "withdraw":
        sibling = mirrors.enable_for_object("items", actor_user_id="operator")
    profile = {"tables": ["public.orders", "public.items"]}
    scope = dict(profile=profile, published_scope=mirrors.read_published_scope(None, source_id))
    authority = dict(previous, owner_epoch=previous["owner_epoch"] + 1,
                     control_revision=previous["control_revision"] + 1, runtime_instance_id="agent-two")
    key = Ed25519PrivateKey.generate()
    proof = token(key, authority=authority, scope=scope, previous_authority=previous)
    receipts = []

    def handler(request):
        payload = json.loads(request.content)
        observed = observe_fence(payload)
        receipts.append((payload, observed["target_fence"]))
        if len(receipts) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"signature": token(
            key, authority=authority, scope=scope, purpose="observation:owner_allocation",
            observation=observed)})

    http = FakeHTTP(handler)
    signals = ReadinessSignals(http, verifier=verifier(key), runtime_instance_id="agent-two",
                               max_age_seconds=30, required_checks=CHECKS, scope=profile)
    request = dict(source_id=source_id, operation_id="cop_new", signed_proof=proof, signals=signals)
    try:
        with pytest.raises(RuntimeBlocked):
            allocate_owner(**request)
        if change == "enroll":
            mirrors.enable_for_object("items", actor_user_id="operator")
        else:
            mirrors.set_enabled(sibling["mirror"]["id"], enabled=False, actor_user_id="operator")
        reconcile_published_scope(source_id)
        assert get_source_store().capture_bindings[source_id]["control_revision"] == previous["control_revision"]
        command = allocate_owner(**request)
        assert command["published_scope"] == scope["published_scope"]
        assert allocate_owner(**request) == command
        assert receipts[0] == receipts[1]
        state = get_source_store().capture_bindings[source_id]
        assert state["owner_epoch"] == authority["owner_epoch"]
        assert state["control_revision"] == authority["control_revision"] + 1
        assert state["published_scope"] == mirrors.read_published_scope(None, source_id)
        assert state["incremental_snapshots"]["active"] is None
        assert state["allocation"]["command"] == command
    finally:
        http.client.close()
