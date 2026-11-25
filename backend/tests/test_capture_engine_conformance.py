"""Offline conformance of every registered capture engine through the registry seam.

One parametrized suite exercises each engine's published interface: profile scope
admission, readiness observation, connector configuration, envelope decoding,
topic naming and publication hand-off checkpoint evidence. It is a contract of this
repository, not qualification of any database version or topology. An engine must
pass here before it is registered.
"""

import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from backend.metadata.capture import profile_support
from backend.metadata.capture.engines import CAPTURE_ENGINE_CODES, capture_authorized, engine_for_entry, mirror_eligible
from backend.metadata.capture.runtime_store import RuntimeBlocked, TablePrerequisiteFailed
from backend.metadata.mirrors.types import PartitionIdentity

HISTORY = {"bootstrap_servers": "kafka.internal:9093", "security": {
    "security.protocol": "SSL", "ssl.truststore.location": "/etc/refraq/ts.p12",
    "ssl.truststore.password": "${file:/etc/refraq/secrets:truststore}",
}}
SECRET = "${file:/etc/refraq/secrets:truststore}"
TLS = {"ca_file": "/etc/refraq/ca.pem", "truststore": "/etc/refraq/ts.p12", "truststore_password": SECRET}
SNAPSHOT = {"notification_topic": "cap.notify", "notification_partition": {
    "runtime_cluster_id": "cluster", "topic_incarnation_id": "inc-notify", "partition": 0}}
REFS = {"username": "${file:/etc/refraq/secrets:user}", "password": "${file:/etc/refraq/secrets:pass}"}
DATA_PARTITIONS = (PartitionIdentity("cluster", "inc-data", 0),)


def registered(code):
    """The engine the runtime selects for a Source entry carrying this engine's profile."""
    return engine_for_entry({f"{code}_profile": {}})


def common(database, tables, **extra):
    return {"source_id": "src_1", "connector_name": "cap-main", "host": "db.internal", "port": 1433,
            "database": database, "tables": tables, "topic_prefix": "cap", "server_version": "fixture-1",
            "history": HISTORY, **extra}


class Case:
    """Per-engine fixtures; the engine behavior under test lives in the registered adapters."""

    def __init__(self, code, *, scope, signal_table, signal_identity, access, connector, collection,
                 source, key_schema_table, evidence, bad_evidence, topic):
        self.code, self.scope_fields, self.signal_table, self.signal_identity = code, scope, signal_table, signal_identity
        self.access, self.connector, self.collection = access, connector, collection
        self.source, self.table, self.evidence, self.bad_evidence, self.topic = source, key_schema_table, evidence, bad_evidence, topic

    @property
    def engine(self):
        return registered(self.code)

    def scope(self, snapshot=False):
        scope = json.loads(json.dumps(self.scope_fields))
        if snapshot:
            scope["snapshot"] = {**SNAPSHOT, "signal_table": self.signal_table,
                                 "signal_relation_identity": self.signal_identity}
        return scope


def evidence(value, witness_key, witness, exclusion):
    return {
        "source_completion": {"notification_topic": "cap.notify", "notification_partition": SNAPSHOT["notification_partition"]},
        "durable_source_checkpoint": {
            "topic": "cap.checkpoints", "partition": {"runtime_cluster_id": "cluster", "topic_incarnation_id": "inc-ckpt", "partition": 0},
            "key": ["cap-main", {"server": "cap"}], "offset": 5, "eof": 9, "value": value,
            witness_key: {**witness, "previous_checkpoint_offset": 2},
        },
        "producer_exclusion": {"source_lineage": ["a", "b", "c", "d"], **exclusion},
    }


def _set(path, replacement):
    def mutate(doc):
        node = doc
        for part in path[:-1]:
            node = node[part]
        node[path[-1]] = replacement
    return mutate


MYSQL_EVIDENCE = evidence(
    {"file": "binlog.000002", "pos": 300}, "binlog_witness",
    {"file": "binlog.000002", "start": 200, "end": 320, "commit_pos": 300},
    {"server_uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "connector_server_id": 20,
     "binlog_file": "binlog.000002", "binlog_position": 400},
)
MSSQL_EVIDENCE = evidence(
    {"commit_lsn": "0000002a:00000010:0003", "change_lsn": "0000002a:00000010:0001"}, "lsn_witness",
    {"change_lsn": "0000002a:00000010:0001", "commit_lsn": "0000002a:00000010:0003", "max_lsn": "0000002a:00000020:0001"},
    {"database": "sales", "capture_instances": ["dbo_orders"], "max_lsn": "0000002a:00000030:0001"},
)
ORACLE_EVIDENCE = evidence(
    {"scn": "1000", "commit_scn": "1005"}, "scn_witness",
    {"scn": "1000", "commit_scn": "1005", "redo_thread": 1},
    {"container": "SALESPDB", "flushed_scn": "1010"},
)
PG_EVIDENCE = evidence(
    {"messageType": "COMMIT", "txId": 7, "lsn": 100, "lsn_proc": 100, "lsn_commit": 100}, "wal_witness",
    {"xid": 7, "wal_start": 90, "wal_end": 110, "commit_lsn": 100},
    {"slot": "refraq_slot", "publication": "refraq_pub", "confirmed_flush_lsn": 120},
)

CASES = [
    Case("mysql", scope=common("sales", ["sales.orders"], server_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                               source_server_id=10, connector_server_id=20, lineage_mode="file",
                               minimum_retention_seconds=600, maximum_binlog_bytes=10**6, maximum_binlog_files=20),
         signal_table="sales.refraq_signal", signal_identity="sales:refraq_signal",
         access={"host": "db.internal", "port": 1433, "database": "sales"},
         connector="io.debezium.connector.mysql.MySqlConnector", collection=lambda t: t,
         source={"connector": "mysql", "db": "sales", "table": "orders"}, key_schema_table="sales.orders",
         evidence=MYSQL_EVIDENCE, topic="cap.sales.orders",
         bad_evidence=[("server", _set(["producer_exclusion", "server_uuid"], "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")),
                       ("position", _set(["durable_source_checkpoint", "binlog_witness", "commit_pos"], 301))]),
    Case("mssql", scope=common("sales", ["dbo.orders"], minimum_retention_seconds=600),
         signal_table="dbo.refraq_signal", signal_identity="5:1234",
         access={"host": "db.internal", "port": 1433, "database": "sales", "schema": "dbo"},
         connector="io.debezium.connector.sqlserver.SqlServerConnector", collection=lambda t: f"sales.{t}",
         source={"connector": "sqlserver", "db": "sales", "schema": "dbo", "table": "orders"},
         key_schema_table="dbo.orders", evidence=MSSQL_EVIDENCE, topic="cap.sales.dbo.orders",
         bad_evidence=[("lsn_order", _set(["producer_exclusion", "max_lsn"], "0000002a:00000010:0002")),
                       ("lsn_format", _set(["durable_source_checkpoint", "value", "commit_lsn"], "42"))]),
    Case("oracle", scope=common("SALESPDB", ["APP.ORDERS"], service_name="salespdb.internal", cdb="CDB1",
                                minimum_retention_seconds=600),
         signal_table="APP.REFRAQ_SIGNAL", signal_identity="1:2",
         access={"host": "db.internal", "port": 1433, "service_name": "salespdb.internal", "owner": "APP"},
         connector="io.debezium.connector.oracle.OracleConnector", collection=lambda t: f"SALESPDB.{t}",
         source={"connector": "oracle", "db": "SALESPDB", "schema": "APP", "table": "ORDERS"},
         key_schema_table="APP.ORDERS", evidence=ORACLE_EVIDENCE, topic="cap.APP.ORDERS",
         bad_evidence=[("flushed", _set(["producer_exclusion", "flushed_scn"], "1004")),
                       ("thread", _set(["durable_source_checkpoint", "scn_witness", "redo_thread"], 0))]),
]
CASE_IDS = [case.code for case in CASES]


# ----- registry and management seam -------------------------------------------------------------

def test_registry_names_every_source_engine_with_a_capture_path():
    assert CAPTURE_ENGINE_CODES == {"postgresql", "mysql", "mssql", "oracle"}


@pytest.mark.parametrize("entry", [{}, {"db2_profile": {}}, {"mysql_profile": {}, "oracle_profile": {}}])
def test_runtime_entry_names_exactly_one_registered_engine(entry):
    with pytest.raises(RuntimeBlocked, match="explicit_capture_engine_required"):
        engine_for_entry(entry)


@pytest.mark.parametrize("code", sorted(CAPTURE_ENGINE_CODES))
def test_runtime_entry_selects_engine_by_profile_key(code):
    assert engine_for_entry({f"{code}_profile": {}, "signing_trust": {}}).code == code


@pytest.mark.parametrize("kwargs,expected", [
    (dict(source_kind="database", engine="oracle", object_type="table", is_present=True), True),
    (dict(source_kind="database", engine="db2", object_type="table", is_present=True), False),
    (dict(source_kind="file", engine="mysql", object_type="table", is_present=True), False),
    (dict(source_kind="database", engine="mssql", object_type="view", is_present=True), False),
    (dict(source_kind="database", engine="postgresql", object_type="table", is_present=False), False),
])
def test_mirror_eligible(kwargs, expected):
    assert mirror_eligible(**kwargs) is expected


def source(**changes):
    values = dict(status="active", engine="mysql", capture_credential_ciphertext="sealed", capture_revision=3)
    return SimpleNamespace(**{**values, **changes})


@pytest.mark.parametrize("candidate,authorized", [
    (source(), True), (None, False), (source(status="disabled"), False), (source(engine="db2"), False),
    (source(capture_credential_ciphertext=None), False), (source(capture_revision=4), False),
])
def test_capture_authorized(candidate, authorized):
    assert capture_authorized(candidate, credential_revision=3) is authorized


# ----- profile admission, readiness and connector configuration ---------------------------------

def profile(case, *, snapshot=False, scope=None, tls=TLS):
    scope = scope or case.scope(snapshot)
    return case.engine.profile(scope=scope, tls=tls, connect=lambda **options: nullcontext(object()))


@pytest.fixture(autouse=True)
def plain_secrets(monkeypatch):
    monkeypatch.setattr(profile_support, "decrypt_secret", lambda value: value)


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
@pytest.mark.parametrize("change", [
    lambda s: s.pop("history"), lambda s: s.update(unexpected=1), lambda s: s.update(tables=[]),
    lambda s: s.update(host="db.internal/;x"), lambda s: s.update(port=0),
    lambda s: s["history"]["security"].update({"ssl.truststore.password": "plaintext"}),
])
def test_profile_rejects_unpinned_or_unsafe_scope(case, change):
    scope = case.scope()
    change(scope)
    with pytest.raises(RuntimeBlocked, match=f"explicit_{case.code}_profile_required"):
        profile(case, scope=scope)


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_profile_requires_secret_reference_for_truststore_password(case):
    with pytest.raises(RuntimeBlocked, match=f"explicit_{case.code}_profile_required"):
        profile(case, tls={**TLS, "truststore_password": "plaintext"})


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_snapshot_signal_table_is_part_of_the_included_tables_but_not_a_mirror_table(case):
    pinned = profile(case, snapshot=True)
    assert pinned.included_tables == [*pinned.scope["tables"], case.signal_table]
    with pytest.raises(RuntimeBlocked, match="explicit_snapshot_profile_required"):
        profile(case, scope={**case.scope(), "snapshot": {**case.scope(True)["snapshot"], "signal_table": case.table}})


def stub_source(case, **changes):
    return SimpleNamespace(id="src_1", engine=case.code, access_ciphertext=json.dumps(case.access),
                           capture_credential_ciphertext=json.dumps({"username": "u", "password": "p"}), **changes)


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_readiness_passes_only_when_every_prerequisite_is_proven(case):
    pinned = profile(case)
    pinned._inspect = lambda connection: ({"cdc": True, "retention": True}, [])
    pinned.validate_source(stub_source(case))
    for results in ({"cdc": True, "retention": None}, {"cdc": False}):
        pinned._inspect = lambda connection, results=results: (results, [])
        with pytest.raises(RuntimeBlocked, match=f"{case.code}_readiness_unconfirmed"):
            pinned.validate_source(stub_source(case))


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_readiness_reports_the_failing_table_distinct_from_unknown(case):
    pinned = profile(case)
    pinned._inspect = lambda connection: ({}, [(case.table, "permission")])
    with pytest.raises(TablePrerequisiteFailed) as failure:
        pinned.validate_source(stub_source(case))
    assert (failure.value.table, failure.value.cause) == (case.table, "permission")


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
@pytest.mark.parametrize("failure", ["engine", "endpoint", "credentials"])
def test_readiness_blocks_wrong_engine_endpoint_or_unreadable_credentials(case, failure):
    pinned = profile(case)
    pinned._inspect = lambda connection: ({"ok": True}, [])
    changes = {"engine": dict(engine="postgresql"), "endpoint": dict(access_ciphertext=json.dumps({**case.access, "host": "other"})),
               "credentials": dict(capture_credential_ciphertext="not json")}[failure]
    candidate = stub_source(case)
    candidate.__dict__.update(changes)
    expected = f"{case.code}_scope_mismatch" if failure == "engine" else f"{case.code}_readiness_unconfirmed"
    with pytest.raises(RuntimeBlocked, match=expected):
        pinned.validate_source(candidate)


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_connector_configuration_is_file_referenced_and_snapshot_wired(case):
    pinned = profile(case, snapshot=True)
    pinned._inspect = lambda connection: ({"ok": True}, [])
    command = {"published_scope": [{"included": True, "qualified_table": case.table}]}
    config = pinned.configuration(command, stub_source(case), REFS)
    assert config["connector.class"] == case.connector
    assert (config["database.user"], config["database.password"]) == (REFS["username"], REFS["password"])
    assert config["topic.prefix"] == "cap" and config["snapshot.mode"] == "no_data"
    assert config["signal.data.collection"] == case.collection(case.signal_table)
    assert config["notification.sink.topic.name"] == "cap.notify"
    assert config["schema.history.internal.kafka.topic"] == "cap.schema"
    assert config["schema.history.internal.consumer.ssl.truststore.password"] == SECRET
    assert case.table.replace(".", r"\.") in config["table.include.list"] or case.table in config["table.include.list"]
    assert all("plaintext" not in str(value) for value in config.values())


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_connector_configuration_blocks_when_no_published_table_is_in_scope(case):
    pinned = profile(case)
    pinned._inspect = lambda connection: ({"ok": True}, [])
    with pytest.raises(RuntimeBlocked, match="connector_published_scope_mismatch"):
        pinned.configuration({"published_scope": [{"included": True, "qualified_table": "other.table"}]},
                             stub_source(case), REFS)


# ----- decoder and topic naming -----------------------------------------------------------------

KEY = {"type": "struct", "fields": [{"field": "id", "type": "int32"}]}
ROW = {"type": "struct", "fields": [{"field": "id", "type": "int32"}, {"field": "body", "type": "string", "optional": True}]}
VALUE = {"type": "struct", "fields": [{**ROW, "field": "before"}, {**ROW, "field": "after"},
                                      {"field": "op", "type": "string"}, {"field": "source", "type": "struct"}]}


def decoder(case):
    schema_name, table_name = case.table.split(".")
    database = case.scope_fields["database"]
    return case.engine.decoder(table_identity="table_1", capture_generation="capture_1", database=database,
                               namespace="cap", schema_name=schema_name, table_name=table_name,
                               connector_version="3.7.1.Final", key_schema=KEY, value_schema=VALUE)


def message(case, op="c", *, source=None, snapshot="false"):
    block = {**case.source, "name": "cap", "version": "3.7.1.Final", "snapshot": snapshot, **(source or {})}
    payload = {"op": op, "source": block,
               "before": {"id": 1, "body": "old"} if op == "d" else None,
               "after": None if op == "d" else {"id": 1, "body": "new"}}
    return json.dumps({"schema": VALUE, "payload": payload}).encode()


KEY_BYTES = json.dumps({"schema": KEY, "payload": {"id": 1}}).encode()


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
@pytest.mark.parametrize("op,snapshot,operation,origin", [
    ("c", "false", "upsert", "live"), ("d", "false", "delete", "live"), ("r", "true", "upsert", "baseline"),
])
def test_decoder_binds_the_envelope_to_an_engine_neutral_record(case, op, snapshot, operation, origin):
    record = decoder(case).decode(offset=3, key=KEY_BYTES, value=message(case, op, snapshot=snapshot))
    assert (record.operation, record.origin, record.key, record.offset) == (operation, origin, {"id": 1}, 3)
    assert (record.table_identity, record.capture_generation) == ("table_1", "capture_1")


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_decoder_tombstone_needs_no_value(case):
    assert decoder(case).decode(offset=0, key=KEY_BYTES, value=None).operation == "tombstone"


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
@pytest.mark.parametrize("change", [
    dict(connector="postgres-lookalike"), dict(table="other"), dict(db="other"), dict(name="other"),
])
def test_decoder_rejects_an_envelope_from_another_source_or_table(case, change):
    with pytest.raises(RuntimeBlocked, match=f"{case.code}_delivery_invalid"):
        decoder(case).decode(offset=0, key=KEY_BYTES, value=message(case, source=change))


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_topic_name_is_derived_from_the_decoder_source(case):
    assert case.engine.topic(decoder(case).source) == case.topic


# ----- publication hand-off checkpoint evidence -------------------------------------------------

def checkpoint_scope(case):
    return case.scope_fields


def confirm(case, doc):
    return case.engine.checkpoint(doc, checkpoint_scope(case), data_topics={"cap.data"},
                                  data_partitions=DATA_PARTITIONS)


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_checkpoint_evidence_is_confirmed(case):
    assert confirm(case, case.evidence)["offset"] == 5


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
@pytest.mark.parametrize("name", ["position", "transport", "ordering", "missing"])
def test_checkpoint_evidence_that_is_unordered_misplaced_or_absent_blocks(case, name):
    doc = json.loads(json.dumps(case.evidence))
    checkpoint = doc["durable_source_checkpoint"]
    witness = next(key for key in checkpoint if key.endswith("_witness"))
    if name == "position":
        checkpoint[witness]["previous_checkpoint_offset"] = checkpoint["offset"]
    elif name == "transport":
        checkpoint["topic"] = "cap.data"
    elif name == "ordering":
        checkpoint["partition"]["topic_incarnation_id"] = "inc-data"
    else:
        del doc["producer_exclusion"]
    with pytest.raises(RuntimeBlocked, match="published_open_checkpoint_unconfirmed"):
        confirm(case, doc)


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_checkpoint_evidence_that_contradicts_the_source_log_position_blocks(case):
    for name, mutate in case.bad_evidence:
        doc = json.loads(json.dumps(case.evidence))
        mutate(doc)
        with pytest.raises(RuntimeBlocked, match="published_open_checkpoint_unconfirmed"):
            confirm(case, doc)


def test_postgresql_checkpoint_evidence_is_confirmed_and_wal_mismatch_blocks():
    scope = {"connector_name": "cap-main", "topic_prefix": "cap", "slot": "refraq_slot", "publication": "refraq_pub"}
    engine = registered("postgresql")
    assert engine.checkpoint(PG_EVIDENCE, scope, data_topics={"cap.data"}, data_partitions=DATA_PARTITIONS)["offset"] == 5
    doc = json.loads(json.dumps(PG_EVIDENCE))
    doc["durable_source_checkpoint"]["wal_witness"]["commit_lsn"] = 101
    with pytest.raises(RuntimeBlocked, match="published_open_checkpoint_unconfirmed"):
        engine.checkpoint(doc, scope, data_topics={"cap.data"}, data_partitions=DATA_PARTITIONS)


def test_gtid_lineage_requires_gtid_set_in_mysql_evidence():
    case = CASES[0]
    scope = {**case.scope_fields, "lineage_mode": "gtid"}
    with pytest.raises(RuntimeBlocked, match="published_open_checkpoint_unconfirmed"):
        case.engine.checkpoint(case.evidence, scope, data_topics={"cap.data"}, data_partitions=DATA_PARTITIONS)
    doc = json.loads(json.dumps(case.evidence))
    doc["durable_source_checkpoint"]["value"]["gtids"] = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:1-9"
    assert case.engine.checkpoint(doc, scope, data_topics={"cap.data"}, data_partitions=DATA_PARTITIONS)


@pytest.mark.parametrize("code", sorted(CAPTURE_ENGINE_CODES))
def test_replacement_baseline_keys_are_engine_specific_and_always_prove_connect_and_kafka(code):
    keys = registered(code).baseline_keys
    assert {"connect", "kafka", "task_running"} <= keys and code in keys
