"""Offline MySQL capture profile contracts, not engine qualification."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy.dialects.mysql import dialect

from backend.core.time import UTC, FixedClock, set_clock, utc_now
from backend.metadata.capture.mysql import MySQLCaptureProfile, MySQLProfileSpec
from backend.metadata.capture.runtime_store import RuntimeBlocked


AUTHORITY = {
    "source_id": "src_test", "binding_id": "cap_test", "owner_epoch": 1,
    "runtime_instance_id": "runtime_test", "capture_generation": 1,
    "control_revision": 2, "credential_revision": 3,
}


@pytest.fixture(autouse=True)
def now(_reset_foundation_singletons):
    instant = datetime(2026, 1, 1, tzinfo=UTC)
    set_clock(FixedClock(instant))
    return instant


def spec(**changes):
    return replace(MySQLProfileSpec(
        profile_id="mysql_candidate", profile_version="1", source_id="src_test",
        scope_version="1", engine_version="8.0.40", connector_version="3.7.1.Final",
        connector_artifact="sha256:" + "a" * 64, transport_version="4.3.1",
        target_version="18.6", topology="single_primary", database="sales",
        tables=("orders",), server_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        source_server_id=10, connector_server_id=20, lineage_mode="file",
        max_age_seconds=30, minimum_retention_seconds=600,
        maximum_binlog_bytes=1000000, maximum_binlog_files=20,
    ), **changes)


def connection(*, variables=None, denied=(), gtid_valid=1):
    values = {
        "version": "8.0.40", "log_bin": "ON", "binlog_format": "ROW",
        "binlog_row_image": "FULL", "server_uuid": spec().server_uuid,
        "server_id": "10", "gtid_mode": "OFF", "binlog_expire_logs_seconds": "3600",
    }
    values.update(variables or {})
    conn = Mock()
    conn.dialect = dialect()

    def execute(statement, parameters=None):
        sql = str(statement)
        if any(marker in sql for marker in denied):
            raise RuntimeError("private driver credentials must not escape")
        result = Mock()
        if "global_variables" in sql:
            result.mappings.return_value.all.return_value = [
                {"VARIABLE_NAME": k, "VARIABLE_VALUE": v} for k, v in values.items()
            ]
        elif "USER_PRIVILEGES" in sql:
            result.scalars.return_value.all.return_value = [
                "REPLICATION SLAVE", "REPLICATION CLIENT",
            ]
        elif sql == "SHOW BINARY LOGS":
            result.mappings.return_value.fetchmany.return_value = [
                {"Log_name": "binlog.000001", "File_size": 400},
                {"Log_name": "binlog.000002", "File_size": 800},
            ]
        else:
            result.scalar.return_value = gtid_valid if "GTID_SUBSET" in sql else 1
        return result

    conn.execute.side_effect = execute
    return conn


def checks(report):
    return {item["key"]: item for item in report["readiness"]}


def position(**changes):
    return {"server_uuid": spec().server_uuid, "file": "binlog.000001",
            "position": 200, **changes}


def inspect(profile, conn=None, saved=None):
    return profile.inspect(conn or connection(), authority=AUTHORITY,
                           saved_position=position() if saved is None else saved)


def resolved(key, *, scope, authority):
    return {"scope": scope, "authority": authority, "verified": True,
            "result": "pass", "ref": "sha256:" + "b" * 64,
            "observed_at": utc_now().isoformat()}


def test_readiness_inspects_binlog_identity_scope_rights_and_retained_file():
    conn = connection()
    profile = MySQLCaptureProfile(spec())
    report = inspect(profile, conn)
    items = checks(report)
    for key in ("binlog_enabled", "row_format", "full_row_image", "server_identity",
                "engine_version", "topology", "scope", "privileges", "lineage",
                "retention", "binlog_capacity"):
        assert items[key]["result"] == "pass", key
        assert items[key]["observed_at"]
        assert items[key]["owner"] and items[key]["action"]
    assert report["source_id"] == "src_test"
    assert report["scope_version"] == "1"
    assert report["profile_version"] == "1"
    assert report["authority"] == AUTHORITY
    assert items["profile_qualified"]["result"] == "unknown"
    with pytest.raises(RuntimeBlocked, match="mysql_readiness_unknown_or_failed"):
        profile.require_admission(report, authority=AUTHORITY)
    calls = conn.execute.call_args_list
    variable_call = next(call for call in calls if "global_variables" in str(call.args[0]))
    assert "log_bin" not in str(variable_call.args[0])
    assert "log_bin" in variable_call.args[1].values()
    assert all(not str(call.args[0]).startswith(("SET", "CREATE", "GRANT", "PURGE"))
               for call in calls)


@pytest.mark.parametrize("variables,key", [
    ({"log_bin": "OFF"}, "binlog_enabled"),
    ({"binlog_format": "MIXED"}, "row_format"),
    ({"binlog_row_image": "MINIMAL"}, "full_row_image"),
    ({"server_id": "11"}, "server_identity"),
    ({"version": "10.11-MariaDB"}, "engine_version"),
    ({"binlog_expire_logs_seconds": "0"}, "retention"),
])
def test_observed_bad_prerequisites_fail(variables, key):
    profile = MySQLCaptureProfile(spec(), proof_resolver=resolved)
    report = inspect(profile, connection(variables=variables))
    assert checks(report)[key]["result"] == "fail"
    with pytest.raises(RuntimeBlocked):
        profile.require_admission(report, authority=AUTHORITY)


@pytest.mark.parametrize("denied,key", [
    (("global_variables",), "row_format"),
    (("USER_PRIVILEGES",), "privileges"),
    (("SHOW BINARY LOGS",), "lineage"),
    (("information_schema.TABLES",), "scope"),
])
def test_inspection_denied_is_unknown_and_redacted(denied, key):
    report = inspect(MySQLCaptureProfile(spec()), connection(denied=denied))
    assert checks(report)[key]["result"] == "unknown"
    assert "private driver" not in repr(report)


@pytest.mark.parametrize("saved", [position(file="binlog.000000"), position(position=900),
                                    position(position=0), position(server_uuid="different")])
def test_missing_or_invalid_file_position_blocks(saved):
    report = inspect(MySQLCaptureProfile(spec()), saved=saved)
    assert checks(report)["lineage"]["result"] == "fail"


@pytest.mark.parametrize("valid,expected", [(1, "pass"), (0, "fail")])
def test_gtid_saved_position_uses_bound_subset_and_purged_checks(valid, expected):
    conn = connection(variables={"gtid_mode": "ON"}, gtid_valid=valid)
    gtid = spec().server_uuid + ":1-40"
    report = inspect(MySQLCaptureProfile(spec(lineage_mode="gtid")), conn,
                     position(gtid_set=gtid))
    assert checks(report)["lineage"]["result"] == expected
    call = next(c for c in conn.execute.call_args_list if "GTID_SUBSET" in str(c.args[0]))
    assert "@@GLOBAL.gtid_purged" in str(call.args[0])
    assert gtid not in str(call.args[0])
    assert call.args[1] == {"saved": gtid}


def test_complete_evidence_admits_but_stale_scope_authority_or_missing_checks_do_not(now):
    profile = MySQLCaptureProfile(spec(), proof_resolver=resolved)
    report = inspect(profile)
    profile.require_admission(report, authority=AUTHORITY)
    for field, value in (("scope_version", "2"), ("profile_version", "2"),
                         ("source_id", "other"), ("authority", {**AUTHORITY, "owner_epoch": 2})):
        altered = {**report, field: value}
        with pytest.raises(RuntimeBlocked):
            profile.require_admission(altered, authority=AUTHORITY)
    for key in checks(report):
        altered = deepcopy(report)
        next(i for i in altered["readiness"] if i["key"] == key)["result"] = "unknown"
        with pytest.raises(RuntimeBlocked):
            profile.require_admission(altered, authority=AUTHORITY)
    stale = deepcopy(report)
    stale["readiness"][0]["observed_at"] = (now - timedelta(seconds=31)).isoformat()
    with pytest.raises(RuntimeBlocked):
        profile.require_admission(stale, authority=AUTHORITY)


@pytest.mark.parametrize("topology,result", [("unknown", "unknown"), ("multi_primary", "fail")])
def test_unsupported_topology_never_admits(topology, result):
    report = inspect(MySQLCaptureProfile(spec(topology=topology), proof_resolver=resolved))
    assert checks(report)["topology"]["result"] == result


@pytest.mark.parametrize("change", [
    {"minimum_retention_seconds": 0}, {"maximum_binlog_bytes": 0},
    {"max_age_seconds": 0}, {"connector_server_id": 10}, {"tables": ()},
])
def test_no_implicit_production_thresholds_or_unscoped_profile(change):
    with pytest.raises(RuntimeBlocked):
        spec(**change)


@pytest.mark.parametrize("field,value", [
    ("verified", False), ("scope", {}), ("authority", {}), ("ref", "unresolved"),
    ("observed_at", timedelta(seconds=-31)),
    ("observed_at", timedelta(seconds=31)),
])
def test_unresolved_mismatched_and_stale_proof_remain_unknown(field, value, now):
    if field == "observed_at":
        value = (now + value).isoformat()

    def resolver(key, **kwargs):
        return {**resolved(key, **kwargs), field: value}
    profile = MySQLCaptureProfile(spec(), proof_resolver=resolver)
    report = inspect(profile)
    assert checks(report)["profile_qualified"]["result"] == "unknown"
    with pytest.raises(RuntimeBlocked):
        profile.require_admission(report, authority=AUTHORITY)


@pytest.mark.parametrize("offset,expected", [
    (-31, "unknown"), (-30, "pass"), (0, "pass"), (1, "unknown"), (31, "unknown"),
])
def test_proof_freshness_boundaries_use_execution_clock(now, offset, expected):
    def resolver(key, **kwargs):
        return {**resolved(key, **kwargs),
                "observed_at": (now + timedelta(seconds=offset)).isoformat()}

    profile = MySQLCaptureProfile(spec(), proof_resolver=resolver)
    report = inspect(profile)
    assert checks(report)["profile_qualified"]["result"] == expected
    if expected == "pass":
        profile.require_admission(report, authority=AUTHORITY)
    else:
        with pytest.raises(RuntimeBlocked, match="mysql_readiness_unknown_or_failed"):
            profile.require_admission(report, authority=AUTHORITY)


def test_admission_rechecks_evidence_age_at_execution(now):
    profile = MySQLCaptureProfile(spec(), proof_resolver=resolved)
    report = inspect(profile)
    assert report["observed_at"] == now.isoformat()
    set_clock(FixedClock(now + timedelta(seconds=30)))
    profile.require_admission(report, authority=AUTHORITY)
    set_clock(FixedClock(now + timedelta(seconds=31)))
    with pytest.raises(RuntimeBlocked, match="mysql_readiness_unknown_or_failed"):
        profile.require_admission(report, authority=AUTHORITY)


@pytest.mark.parametrize("limit", [{"maximum_binlog_bytes": 100}, {"maximum_binlog_files": 1}])
def test_explicit_binlog_capacity_limits_block(limit):
    profile = MySQLCaptureProfile(spec(**limit), proof_resolver=resolved)
    report = inspect(profile)
    assert checks(report)["binlog_capacity"]["result"] == "fail"
    with pytest.raises(RuntimeBlocked):
        profile.require_admission(report, authority=AUTHORITY)


def test_exact_allowlisted_debezium_configuration_and_revision_scoped_secret_refs():
    profile = MySQLCaptureProfile(spec(), proof_resolver=resolved)
    report = inspect(profile)
    config = profile.connector_config(
        report, authority=AUTHORITY, host="mysql.internal", port=3306,
        topic_prefix="refraq.cap_test.g1", history_topic="refraq.cap_test.g1.schema",
        history_bootstrap_servers="broker.internal:9093",
        history_security_refs={"ssl.truststore.location": "truststore",
                               "ssl.truststore.password": "truststore_password",
                               "ssl.keystore.location": "keystore",
                               "ssl.keystore.password": "keystore_password",
                               "ssl.key.password": "key_password"},
    )
    secret = "${file:/run/refraq/capture/cap_test/credentials-r3.properties:"
    transport = "${file:/run/refraq/capture/cap_test/transport-r3.properties:"
    expected = {
        "connector.class": "io.debezium.connector.mysql.MySqlConnector",
        "tasks.max": "1", "database.hostname": "mysql.internal", "database.port": "3306",
        "database.user": secret + "username}", "database.password": secret + "password}",
        "database.server.id": "20", "database.include.list": "sales",
        "table.include.list": r"sales\.orders", "topic.prefix": "refraq.cap_test.g1",
        "database.ssl.mode": "verify_identity", "snapshot.mode": "no_data",
        "snapshot.locking.mode": "none", "signal.enabled.channels": "kafka",
        "signal.kafka.topic": "refraq.cap_test.g1.signal",
        "signal.kafka.bootstrap.servers": "broker.internal:9093",
        "schema.history.internal.kafka.bootstrap.servers": "broker.internal:9093",
        "schema.history.internal.kafka.topic": "refraq.cap_test.g1.schema",
        "include.schema.changes": "true", "tombstones.on.delete": "true",
        "decimal.handling.mode": "precise", "bigint.unsigned.handling.mode": "precise",
        "time.precision.mode": "adaptive_time_microseconds", "binary.handling.mode": "bytes",
        "database.ssl.keystore": secret + "keystore}",
        "database.ssl.keystore.password": secret + "keystore_password}",
        "database.ssl.truststore": secret + "truststore}",
        "database.ssl.truststore.password": secret + "truststore_password}",
    }
    for prefix in ("schema.history.internal.producer.", "schema.history.internal.consumer.",
                   "signal.consumer."):
        expected[prefix + "security.protocol"] = "SSL"
        expected[prefix + "ssl.endpoint.identification.algorithm"] = "https"
        for key, ref in {"ssl.truststore.location": "truststore",
                         "ssl.truststore.password": "truststore_password",
                         "ssl.keystore.location": "keystore",
                         "ssl.keystore.password": "keystore_password",
                         "ssl.key.password": "key_password"}.items():
            expected[prefix + key] = transport + ref + "}"
    assert config == expected
    with pytest.raises(RuntimeBlocked):
        profile.connector_config(report, authority={**AUTHORITY, "credential_revision": 4},
                                 host="mysql.internal", port=3306,
                                 topic_prefix="refraq.cap_test.g1", history_topic="history",
                                 history_bootstrap_servers="broker:9093", history_security_refs={})
