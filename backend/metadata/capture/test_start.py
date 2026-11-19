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
from backend.metadata.capture.control import AUTHORITY_KEYS, allocate_owner, capture_status
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
    with mirror_store.transaction() as session:
        mirrors.ensure_open_intent(session, operation_id="open", channel_id="workflow",
                                   channel_version=1, object_ids=["orders"])
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


@pytest.mark.parametrize("wal", ["logical", "replica"])
def test_postgresql_profile_inspects_capture_identity_before_config(managed_command, monkeypatch, wal):
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "offline-test-only")
    get_settings.cache_clear()
    source = get_source_store().get_source(managed_command["source_id"])
    source.access_ciphertext = encrypt_secret(json.dumps({"host": "pg.internal", "port": 5432, "database": "app", "schema": "public"}))
    source.capture_credential_ciphertext = encrypt_secret(json.dumps({"username": "capture", "password": "private"}))
    scope = {"source_id": source.id, "connector_name": "cap_one", "host": "pg.internal",
             "port": 5432, "database": "app", "tables": ["public.orders"],
             "publication": "capture_pub", "slot": "capture_slot", "topic_prefix": "cap_one",
             "server_version_num": 180000}

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
            if "current_database" in self.sql:
                return ("app", wal, 180000, True, False)
            if "pg_publication WHERE" in self.sql:
                return (False, True, True, True, True)
            if "pg_replication_slots" in self.sql:
                return ("pgoutput", "app", False)
            return (True,)

        def fetchall(self):
            return [("public.orders", False, ["body", "id"], ["id", "body"], False)]

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
        assert config["publication.autocreate.mode"] == "disabled"
        assert "private" not in config.values()
    get_settings.cache_clear()
