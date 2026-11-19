"""Offline Kafka client and recording Application tests; no broker or SQL calls."""

import base64
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from backend.metadata.capture import delivery as delivery_module
from backend.metadata.capture.decoder import PostgreSQLDecoder, TOAST
from backend.metadata.capture.delivery import (
    DeliveryBinding, DeliveryLimits, KafkaDelivery, KafkaIdentity, open_delivery,
)
from backend.metadata.capture.runtime_store import RuntimeBlocked
from backend.metadata.mirrors.types import Authority, PartitionIdentity


KEY = {"type": "struct", "fields": [{"field": "id", "type": "int32"}]}
ROW = {"type": "struct", "fields": [
    {"field": "id", "type": "int32"},
    {"field": "body", "type": "string", "optional": True},
]}
SCHEMA = {"type": "struct", "fields": [
    {**ROW, "field": "before"}, {**ROW, "field": "after"},
    {"field": "op", "type": "string"}, {"field": "source", "type": "struct"},
]}
SOURCE = {"connector": "postgresql", "version": "3.4.0.Final", "name": "cap",
          "db": "db", "schema": "public", "table": "items", "snapshot": "false"}
BINDING = DeliveryBinding(
    Authority("source", "binding", 1, "runtime", 1, 1, "capture"), "generation",
    PartitionIdentity("cluster", "incarnation", 0), "cap.public.items",
)


def decoder(key_schema=KEY, value_schema=SCHEMA):
    return PostgreSQLDecoder(table_identity="table", capture_generation="capture",
                             database="db", namespace="cap", schema_name="public",
                             table_name="items", connector_version="3.4.0.Final",
                             key_schema=key_schema, value_schema=value_schema)


def wire_key(id=1):
    return json.dumps({"schema": KEY, "payload": {"id": id}}).encode()


def envelope(op="c", id=1, body="data", snapshot="false"):
    return {"schema": SCHEMA, "payload": {
        "op": op, "source": {**SOURCE, "snapshot": snapshot},
        "before": {"id": id, "body": "old"} if op in {"u", "d"} else None,
        "after": None if op == "d" else {"id": id, "body": body},
    }}


def decode(doc, key=wire_key()):
    return decoder().decode(offset=0, key=key, value=json.dumps(doc).encode())


@pytest.mark.parametrize("op,snapshot,operation,origin", [
    ("c", "false", "upsert", "live"), ("u", False, "upsert", "live"),
    ("d", "false", "delete", "live"), ("r", True, "upsert", "baseline"),
    ("r", "last", "upsert", "baseline"), ("r", "incremental", "upsert", "baseline"),
])
def test_operations(op, snapshot, operation, origin):
    record = decode(envelope(op, snapshot=snapshot))
    assert (record.operation, record.origin, record.key) == (operation, origin, {"id": 1})


def test_toast_preserves_old_column_without_placeholder_replacement():
    record = decode(envelope("u", body=TOAST))
    assert record.values == {"id": 1}
    assert record.unchanged_columns == ("body",)
    assert decode(envelope("u", body=None)).values["body"] is None
    with pytest.raises(RuntimeBlocked):
        decode(envelope("c", body=TOAST))


@pytest.mark.parametrize("mutate", [
    lambda d: d["payload"].update(op="t"),
    lambda d: d["payload"]["source"].update(snapshot=None),
    lambda d: d["payload"]["source"].update(table="other"),
    lambda d: d["payload"]["source"].update(version="unknown"),
    lambda d: d["payload"]["after"].update(id=2),
    lambda d: d["payload"]["after"].update(id=True),
    lambda d: d["payload"]["after"].update(id=2 ** 31),
    lambda d: d["payload"]["after"].update(extra="private-value"),
    lambda d: d["schema"].update(name="unexpected"),
])
def test_invalid_envelope_is_safe(mutate):
    doc = deepcopy(envelope())
    mutate(doc)
    with pytest.raises(RuntimeBlocked, match="^postgresql_delivery_invalid$"):
        decode(doc)


def test_key_change_must_be_ordered_delete_and_create_not_update():
    doc = envelope("u")
    doc["payload"]["before"]["id"] = 2
    with pytest.raises(RuntimeBlocked):
        decode(doc)
    assert decode(envelope("d", id=2), wire_key(2)).operation == "delete"
    assert decoder().decode(offset=1, key=wire_key(2), value=None).operation == "tombstone"
    assert decode(envelope("c", id=3), wire_key(3)).key == {"id": 3}


@pytest.mark.parametrize("key", [b"null", b"{}", b'{"schema":{},"payload":{}}',
                                 wire_key(None), wire_key(True), wire_key("1")])
def test_invalid_key(key):
    with pytest.raises(RuntimeBlocked):
        decode(envelope(), key)


@pytest.mark.parametrize("kind,name,raw,expected,parameters", [
    ("bytes", "org.apache.kafka.connect.data.Decimal", base64.b64encode(b"\x04\xd2").decode(), "12.34", {"scale": "2"}),
    ("bytes", None, "AP8=", "\\x00ff", None),
    ("int32", "io.debezium.time.Date", 1, "1970-01-02", None),
    ("int64", "io.debezium.time.MicroTime", 1000001, "00:00:01.000001", None),
    ("int64", "io.debezium.time.MicroTimestamp", 1, "1970-01-01T00:00:00.000001", None),
    ("string", "io.debezium.time.ZonedTimestamp", "2026-01-01T08:00:00+08:00", "2026-01-01T00:00:00+00:00", None),
    ("string", "io.debezium.data.Json", '{"a":1}', {"a": 1}, None),
])
def test_typed_postgresql_values(kind, name, raw, expected, parameters):
    schema = deepcopy(SCHEMA)
    for side in (0, 1):
        field = {"field": "body", "type": kind, "optional": True}
        if name:
            field["name"] = name
        if parameters:
            field["parameters"] = parameters
        schema["fields"][side]["fields"][1] = field
    doc = envelope(body=raw)
    doc["schema"] = schema
    record = decoder(value_schema=schema).decode(offset=0, key=wire_key(), value=json.dumps(doc).encode())
    assert record.values["body"] == expected


@pytest.mark.parametrize("field", [
    {"field": "body", "type": "array", "items": {"type": "string"}},
    {"field": "body", "type": "int64", "name": "unsupported"},
    {"field": "body", "type": "bytes", "name": "org.apache.kafka.connect.data.Decimal", "parameters": {"scale": "1001"}},
])
def test_unsupported_schema_rejected_before_poll(field):
    schema = deepcopy(SCHEMA)
    schema["fields"][1]["fields"][1] = field
    schema["fields"][0]["fields"][1] = field
    with pytest.raises(RuntimeBlocked):
        decoder(value_schema=schema)


class Message:
    def __init__(self, offset, doc=None, *, key=1, tombstone=False):
        self.n = offset
        self.doc = doc if doc is not None else envelope(id=key)
        self.k = key
        self.tombstone = tombstone

    def offset(self):
        return self.n

    def topic(self):
        return BINDING.topic

    def partition(self):
        return 0

    def error(self):
        return None

    def key(self):
        return wire_key(self.k)

    def value(self):
        return None if self.tombstone else json.dumps(self.doc).encode()

    def headers(self):
        return []


class FakeConsumer:
    def __init__(self, messages, events):
        self.messages = messages
        self.events = events
        self.ack_failure = False
        self.low = 0
        self.polled = 0
        self.closed = False

    def assign(self, partitions):
        self.next = partitions[0].offset
        self.events.append(("seek", self.next))

    def get_watermark_offsets(self, *args, **kwargs):
        return self.low, 1000

    def poll(self, timeout):
        self.polled += 1
        message = next((m for m in self.messages if m.n >= self.next), None)
        if message:
            self.next = message.n + 1
        return message

    def pause(self, partitions):
        self.events.append(("pause",))

    def commit(self, *, offsets, asynchronous):
        assert not asynchronous
        self.events.append(("ack", offsets[0].offset))
        if self.ack_failure:
            raise RuntimeError("private-value")
        return [SimpleNamespace(error=None)]

    def unassign(self):
        self.events.append(("unassign",))

    def close(self):
        self.closed = True


class RecordingApplication:
    def __init__(self, events):
        self.offset = -1
        self.events = events
        self.records = []
        self.fail = False

    def apply_batch(self, **kwargs):
        records = kwargs["records"]
        assert kwargs["authority"] == BINDING.authority
        assert kwargs["partition_identity"] == BINDING.partition_identity
        if self.fail:
            raise RuntimeError("private-value")
        self.events.append(("target", tuple(r.offset for r in records)))
        if records:
            assert records[0].offset == self.offset + 1
            self.records.extend(records)
            self.offset = records[-1].offset
        return {"offset": self.offset, "commit_seq": 1}


@contextmanager
def admission(**kwargs):
    assert set(kwargs) == {"binding", "decoder", "limits"}
    yield


def runtime(messages, **kwargs):
    events = []
    client = FakeConsumer(messages, events)
    app = RecordingApplication(events)
    identity = SimpleNamespace(verify=lambda *args: events.append(("identity",)))
    delivery = KafkaDelivery(consumer=client, identity=identity, application=app,
                             binding=BINDING, decoder=decoder(), admission=admission, **kwargs)
    return delivery, client, app, events


def test_commit_before_ack_and_target_seek_not_group_offset():
    delivery, client, app, events = runtime([Message(0), Message(1)])
    assert delivery.poll_once() == 2
    assert events.index(("target", (0, 1))) < events.index(("ack", 2))
    assert ("seek", 0) in events
    assert delivery.poll_once() == 0
    assert ("seek", 2) in events
    assert len(app.records) == 2


def test_bad_last_record_rolls_back_whole_offline_batch_before_application():
    bad = envelope()
    bad["payload"]["op"] = "t"
    delivery, client, app, events = runtime([Message(0), Message(1, bad)])
    with pytest.raises(RuntimeBlocked, match="^capture_delivery_blocked$"):
        delivery.poll_once()
    assert app.offset == -1 and not app.records
    assert not any(e[0] == "ack" for e in events)
    client.messages[1] = Message(1)
    assert delivery.poll_once() == 2


def test_ack_failure_after_target_commit_reseeks_without_duplicate_effects():
    delivery, client, app, events = runtime([Message(0)])
    client.ack_failure = True
    with pytest.raises(RuntimeBlocked):
        delivery.poll_once()
    assert app.offset == 0
    client.ack_failure = False
    assert delivery.poll_once() == 0
    assert len(app.records) == 1 and ("seek", 1) in events


def test_outage_does_not_poll_or_ack_then_resumes_from_target():
    delivery, client, app, events = runtime([Message(0)])
    app.fail = True
    with pytest.raises(RuntimeBlocked):
        delivery.poll_once()
    assert client.polled == 0 and not app.records
    app.fail = False
    assert delivery.poll_once() == 1


@pytest.mark.parametrize("messages", [[Message(1)], [Message(0), Message(2)]])
def test_offset_gaps_never_advance_target(messages):
    delivery, client, app, events = runtime(messages)
    with pytest.raises(RuntimeBlocked):
        delivery.poll_once()
    assert app.offset == -1


def test_retention_gap_blocks_before_poll():
    delivery, client, app, events = runtime([Message(0)])
    client.low = 1
    with pytest.raises(RuntimeBlocked):
        delivery.poll_once()
    assert client.polled == 0 and app.offset == -1


def test_ordered_key_change_delete_tombstone_create():
    delivery, client, app, events = runtime([
        Message(0, envelope("d", id=1)), Message(1, key=1, tombstone=True),
        Message(2, key=2),
    ])
    assert delivery.poll_once() == 3
    assert [(r.operation, r.key) for r in app.records] == [
        ("delete", {"id": 1}), ("tombstone", {"id": 1}), ("upsert", {"id": 2}),
    ]


def test_bounded_batches_and_capacity_no_drop():
    delivery, client, app, events = runtime([Message(0), Message(1), Message(2)],
                                          limits=DeliveryLimits(max_records=1))
    assert [delivery.poll_once() for _ in range(3)] == [1, 1, 1]
    assert [r.offset for r in app.records] == [0, 1, 2]
    delivery, client, app, events = runtime([Message(0, envelope(body="x" * 2000))],
                                          limits=DeliveryLimits(max_record_bytes=100, max_batch_bytes=100))
    with pytest.raises(RuntimeBlocked):
        delivery.poll_once()
    assert app.offset == -1


def test_authority_rejection_before_any_target_or_poll_effect():
    delivery, client, app, events = runtime([Message(0)])

    @contextmanager
    def deny(**kwargs):
        raise RuntimeError("private-value")
        yield

    delivery.admission = deny
    with pytest.raises(RuntimeBlocked, match="^capture_delivery_blocked$"):
        delivery.poll_once()
    assert not events and client.polled == 0


def test_shutdown_after_poll_commits_collected_prefix_and_no_more_poll():
    delivery, client, app, events = runtime([Message(0), Message(1)])
    poll = client.poll

    def stop_poll(timeout):
        message = poll(timeout)
        delivery.stop()
        return message

    client.poll = stop_poll
    assert delivery.poll_once() == 1
    assert app.offset == 0
    assert delivery.poll_once() == 0
    delivery.close()
    assert client.closed
    resumed, _, app2, _ = runtime(client.messages)
    app2.offset = app.offset
    assert resumed.poll_once() == 1


@pytest.mark.parametrize("limits", [DeliveryLimits(max_records=0), DeliveryLimits(max_batch_bytes=0),
                                    DeliveryLimits(poll_seconds=0), DeliveryLimits(queue_kbytes=0)])
def test_bad_capacity_rejected(limits):
    with pytest.raises(RuntimeBlocked):
        runtime([], limits=limits)


def test_identity_uses_immutable_ids_and_single_partition():
    class Future:
        def __init__(self, value):
            self.value = value

        def result(self, **kwargs):
            return self.value

    topic = SimpleNamespace(topic_id="incarnation", partitions=[SimpleNamespace(id=0)])
    admin = SimpleNamespace(
        describe_cluster=lambda **kw: Future(SimpleNamespace(cluster_id="cluster")),
        describe_topics=lambda *args, **kw: {BINDING.topic: Future(topic)},
    )
    identity = KafkaIdentity(admin)
    identity.verify(BINDING, 1)
    for bad in [replace(BINDING, partition_identity=PartitionIdentity("wrong", "incarnation", 0)),
                replace(BINDING, partition_identity=PartitionIdentity("cluster", "old", 0))]:
        with pytest.raises(RuntimeBlocked):
            identity.verify(bad, 1)
    topic.partitions.append(SimpleNamespace(id=1))
    with pytest.raises(RuntimeBlocked):
        identity.verify(BINDING, 1)


def test_real_composition_wires_application_and_safety_settings(monkeypatch):
    captured = {}

    def consumer(config):
        captured.update(config)
        return FakeConsumer([], [])

    monkeypatch.setattr(delivery_module, "Consumer", consumer)
    monkeypatch.setattr(delivery_module, "AdminClient", lambda config: object())
    engine = object()
    delivery = open_delivery(kafka_config={"bootstrap.servers": "broker:9093", "security.protocol": "SSL",
                                          "ssl.ca.location": "/protected/ca"}, group_id="delivery",
                             applier_engine=engine, binding=BINDING, decoder=decoder(), admission=admission)
    assert delivery.application.engine is engine
    assert captured["enable.auto.commit"] is False
    assert captured["enable.auto.offset.store"] is False
    assert captured["auto.offset.reset"] == "error"
    assert captured["allow.auto.create.topics"] is False
    assert captured["ssl.endpoint.identification.algorithm"] == "https"
    assert captured["log_level"] == 0
    assert not captured["logger"].propagate
    delivery.close()


def test_boolean_schema_metadata_is_not_integer_metadata():
    schema = deepcopy(SCHEMA)
    schema["fields"][1]["fields"][1]["optional"] = 1
    doc = envelope()
    doc["schema"] = schema
    with pytest.raises(RuntimeBlocked):
        decode(doc)


@pytest.mark.parametrize("body", [123, True, [], {}])
def test_delete_validates_before_non_key_types(body):
    doc = envelope("d")
    doc["payload"]["before"]["body"] = body
    with pytest.raises(RuntimeBlocked):
        decode(doc)


def test_bytes_toast_is_not_written_as_literal_placeholder():
    schema = deepcopy(SCHEMA)
    for side in (0, 1):
        schema["fields"][side]["fields"][1]["type"] = "bytes"
    doc = envelope("u", body=base64.b64encode(TOAST.encode()).decode())
    doc["schema"] = schema
    doc["payload"]["before"]["body"] = None
    record = decoder(value_schema=schema).decode(offset=0, key=wire_key(), value=json.dumps(doc).encode())
    assert record.values == {"id": 1} and record.unchanged_columns == ("body",)


def test_json_exponent_overflow_is_rejected_before_target():
    schema = deepcopy(SCHEMA)
    for side in (0, 1):
        schema["fields"][side]["fields"][1]["name"] = "io.debezium.data.Json"
    doc = envelope(body='{"value":1e999}')
    doc["schema"] = schema
    with pytest.raises(RuntimeBlocked, match="^postgresql_delivery_invalid$"):
        decoder(value_schema=schema).decode(offset=0, key=wire_key(), value=json.dumps(doc).encode())


def test_duplicate_json_fields_rejected():
    with pytest.raises(RuntimeBlocked):
        decoder().decode(offset=0, key=wire_key(), value=b'{"schema":{},"schema":{}}')


def test_topic_recreation_between_poll_and_apply_has_no_row_or_ack_effect():
    delivery, client, app, events = runtime([Message(0)])
    calls = []

    def verify(*args):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("private-value")

    delivery.identity.verify = verify
    with pytest.raises(RuntimeBlocked):
        delivery.poll_once()
    assert app.offset == -1 and not any(e[0] == "ack" for e in events)


def test_constructor_cleanup_failure_does_not_leak_driver_exception(monkeypatch):
    class Client:
        def close(self):
            raise RuntimeError("private-password")

    monkeypatch.setattr(delivery_module, "Consumer", lambda config: Client())
    monkeypatch.setattr(delivery_module, "AdminClient", lambda config: object())
    monkeypatch.setattr(delivery_module, "Application", lambda engine: (_ for _ in ()).throw(ValueError("private-value")))
    with pytest.raises(RuntimeBlocked, match="^capture_delivery_configuration_invalid$"):
        open_delivery(kafka_config={"bootstrap.servers": "broker:9093", "security.protocol": "SSL",
                                    "ssl.ca.location": "/protected/ca"}, group_id="delivery",
                      applier_engine=object(), binding=BINDING, decoder=decoder(), admission=admission)


@pytest.mark.parametrize("value", [True, "1", float("nan"), float("inf")])
def test_poll_capacity_requires_finite_number(value):
    with pytest.raises(RuntimeBlocked):
        runtime([], limits=DeliveryLimits(poll_seconds=value))
