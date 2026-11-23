"""Offline process composition with signed leases and real client API objects."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
import time
from types import SimpleNamespace

from confluent_kafka import TopicCollection, TopicPartition, TopicPartitionInfo, Uuid
from confluent_kafka.admin import TopicDescription
import jwt
import pytest

from backend.core.time import utc_now
from backend.metadata.capture import delivery_composition as composition
from backend.metadata.capture.delivery import DeliveryLimits, KafkaDelivery
from backend.metadata.capture.runtime import CaptureRuntime
from backend.metadata.capture.runtime_store import CommandJournal, RuntimeBlocked
from backend.metadata.capture.test_delivery import (
    BINDING, FakeConsumer, Message, RecordingApplication, decoder,
)
from backend.metadata.capture.test_runtime import TRUST, SIGNING_KEY


def setup_delivery(monkeypatch, tmp_path):
    dec = decoder()
    table = {"authority": asdict(BINDING.authority), "generation_id": "generation",
             "partition_identity": asdict(BINDING.partition_identity), "topic": BINDING.topic,
             "schema_fingerprint": "fingerprint", "native_types": {"id": "integer", "body": "text"},
             "decoder": {"table_identity": "table", "capture_generation": "capture", "database": "db",
                         "namespace": "cap", "schema_name": "public", "table_name": "items",
                         "connector_version": "3.4.0.Final", "key_schema": dec.key_schema,
                         "value_schema": dec.value_schema}}
    metadata = {"generation_id": "generation", "authority": table["authority"],
                "table_identity": "table", "capture_generation": "capture",
                "schema_fingerprint": "fingerprint", "key_columns": ["id"],
                "column_names": ["id", "body"], "native_types": table["native_types"],
                "partition_identity": table["partition_identity"], "cleanup_pending": False,
                "status": "published"}
    state = {**asdict(BINDING.authority), "binding_id": "binding", "desired": "configured"}
    state.pop("resource_binding_id")
    state["published_scope"] = [dict(mirror_id="mirror", qualified_table="public.items",
                                     table_identity="table", mirror_revision=1, included=True)]
    source = SimpleNamespace(status="active", capture_credential_ciphertext="encrypted", capture_revision=1)
    events = []
    held = {"management": False}

    @contextmanager
    def transaction(source_id):
        held["management"] = True
        try:
            yield None, source
        finally:
            held["management"] = False

    class Gateway:
        def request(self, method, path, payload):
            assert held["management"]
            if path.endswith("release"):
                events.append(("release",))
                return None
            events.append(("lease",))
            now = utc_now()
            return {"signature": jwt.encode({
                "iss": "gateway", "aud": "capture", "iat": now, "nbf": now,
                "exp": now + timedelta(seconds=180), "jti": "lease",
                "purpose": "delivery_lease", "authority": payload["authority"],
                "scope": payload["scope"], "operation_id": payload["operation_id"],
                "facts": {key: True for key in composition.FACTS},
                "observed_at": time.time(), "lease_id": "held-lease",
            }, SIGNING_KEY, algorithm="EdDSA", headers={"kid": "trusted"})}

    owner = object.__new__(composition.SourceDelivery)
    owner.settings = {"target": {"timeout_seconds": 2}}
    owner.tables = owner.manifest_tables = [table]
    owner.source_id = "source"
    owner.journal = CommandJournal(tmp_path)
    owner.signals = SimpleNamespace(runtime_instance_id="runtime", http=Gateway())
    owner.verifier = TRUST
    owner.profile = SimpleNamespace(scope={"database": "db", "topic_prefix": "cap", "tables": ["public.items"]})
    owner.max_age = 10
    owner.engine = SimpleNamespace(dispose=lambda: None)
    owner.limits = DeliveryLimits()
    owner.resume_operation_id = None
    owner.retained = {}
    owner.client_generations = {table["generation_id"]}
    owner.stamp = deepcopy(state)
    owner.stamp.pop("desired")
    owner.stamp.pop("published_scope")
    monkeypatch.setattr(composition, "source_control_transaction", transaction)
    monkeypatch.setattr(composition, "load_binding", lambda *args: state)
    monkeypatch.setattr(composition, "read_dispatch_scope", lambda *args, **kwargs: state["published_scope"])
    monkeypatch.setattr(composition, "target_metadata", lambda *args: metadata)
    consumer = FakeConsumer([Message(0)], events)
    app = RecordingApplication(events)
    original = consumer.commit

    def commit(**kwargs):
        assert held["management"]
        with pytest.raises(RuntimeBlocked):
            with owner.journal.source_lock("source"):
                pytest.fail("source lock not retained through acknowledgment")
        return original(**kwargs)

    consumer.commit = commit
    client = KafkaDelivery(consumer=consumer, identity=SimpleNamespace(verify=lambda *a: None),
                           application=app, binding=BINDING, decoder=dec,
                           admission=owner.admission)
    owner.clients = [client]
    runtime = CaptureRuntime(journal=owner.journal, connect=None, signals=None, delivery=owner)
    monkeypatch.setattr(runtime, "poll_source", lambda source_id: "idle")
    return runtime, owner, state, source, metadata, events


def test_runtime_idle_control_still_applies_then_acks_under_signed_lease(monkeypatch, tmp_path):
    runtime, owner, state, source, metadata, events = setup_delivery(monkeypatch, tmp_path)
    try:
        assert runtime.poll_once("source") == "idle"
        assert events.index(("target", (0,))) < events.index(("ack", 1)) < events.index(("release",))
    finally:
        owner.close()
        owner.journal.close()


@pytest.mark.parametrize("change", ["disabled", "revision", "owner", "schema", "topic", "key", "scope"])
def test_denied_current_authority_retires_before_effects(monkeypatch, tmp_path, change):
    runtime, owner, state, source, metadata, events = setup_delivery(monkeypatch, tmp_path)
    if change == "disabled":
        source.status = "disabled"
    elif change == "revision":
        source.capture_revision = 2
    elif change == "owner":
        state["owner_epoch"] = 2
    elif change == "schema":
        metadata["schema_fingerprint"] = "changed"
    elif change == "topic":
        metadata["partition_identity"] = {**metadata["partition_identity"], "topic_incarnation_id": "changed"}
    elif change == "scope":
        owner.profile.scope["tables"].append("public.unpublished")
    else:
        metadata["key_columns"] = ["body"]
    try:
        with pytest.raises(RuntimeBlocked):
            runtime.poll_once("source")
        assert owner.clients == []
        assert not any(event[0] in {"target", "ack"} for event in events)
    finally:
        owner.close()
        owner.journal.close()


def test_missing_signature_is_not_admission(monkeypatch, tmp_path):
    runtime, owner, *rest = setup_delivery(monkeypatch, tmp_path)
    owner.signals.http.request = lambda *args: {"verified": True}
    try:
        with pytest.raises(RuntimeBlocked):
            runtime.poll_once("source")
        assert not any(event[0] in {"target", "ack"} for event in rest[-1])
    finally:
        owner.close()
        owner.journal.close()


def test_installed_confluent_metadata_objects_without_network():
    partition = TopicPartition("topic", 0, 1)
    assert partition.error is None
    assert TopicCollection(["topic"]).topic_names == ["topic"]
    topic = TopicDescription("topic", Uuid(0, 1), False, [TopicPartitionInfo(0, None, [], [])])
    assert topic.partitions[0].id == 0
    assert str(topic.topic_id)
