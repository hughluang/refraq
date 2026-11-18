"""Candidate MySQL capture profile; no runtime registration or support claim.

The manager supplies a restricted SQLAlchemy connection using the capture
identity, never an administrative or ordinary Source query identity. Independent
checks come from a composition-bound proof resolver, not user configuration.
"""

from dataclasses import dataclass
from datetime import datetime
import re

from sqlalchemy import text

from backend.core.time import utc_now
from backend.metadata.capture.control import AUTHORITY_KEYS
from backend.metadata.capture.runtime_store import RuntimeBlocked


VARIABLES = (
    "version", "log_bin", "binlog_format", "binlog_row_image", "server_uuid",
    "server_id", "gtid_mode", "binlog_expire_logs_seconds",
)
INDEPENDENT_CHECKS = frozenset({
    "profile_qualified", "topology_verified", "retention_verified", "source_pressure",
    "scan_bounded", "delivery_bounded", "credential_valid", "alarm_drill",
    "owner_excluded", "target_fenced", "schema_observation", "publication_barrier",
    "key_type_mapping", "snapshot_supported", "connector_server_id_unique",
})
SQL_CHECKS = frozenset({
    "engine_version", "topology", "binlog_enabled", "row_format", "full_row_image",
    "server_identity", "scope", "privileges", "lineage", "retention", "binlog_capacity",
})


@dataclass(frozen=True)
class MySQLProfileSpec:
    profile_id: str
    profile_version: str
    source_id: str
    scope_version: str
    engine_version: str
    connector_version: str
    connector_artifact: str
    transport_version: str
    target_version: str
    topology: str
    database: str
    tables: tuple[str, ...]
    server_uuid: str
    source_server_id: int
    connector_server_id: int
    lineage_mode: str
    max_age_seconds: int
    minimum_retention_seconds: int
    maximum_binlog_bytes: int
    maximum_binlog_files: int

    def __post_init__(self):
        strings = (self.profile_id, self.profile_version, self.source_id,
                   self.scope_version, self.engine_version, self.connector_version,
                   self.transport_version, self.target_version, self.database)
        numbers = (self.source_server_id, self.connector_server_id, self.max_age_seconds,
                   self.minimum_retention_seconds, self.maximum_binlog_bytes,
                   self.maximum_binlog_files)
        if (any(not isinstance(v, str) or not v for v in strings)
                or any(type(v) is not int or v <= 0 for v in numbers)
                or not 0 < self.connector_server_id < 2**32
                or self.source_server_id == self.connector_server_id
                or self.lineage_mode not in {"file", "gtid"}
                or not isinstance(self.tables, tuple) or not self.tables
                or any(not isinstance(v, str) or not v or "," in v for v in self.tables)
                or len(set(self.tables)) != len(self.tables)
                or "," in self.database
                or not re.fullmatch(r"[0-9a-fA-F-]{36}", self.server_uuid)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.connector_artifact)):
            raise RuntimeBlocked("explicit_mysql_profile_required")


class MySQLCaptureProfile:
    def __init__(self, spec, *, proof_resolver=None):
        self.spec = spec
        self.proof_resolver = proof_resolver

    def scope(self):
        p = self.spec
        return {"source_id": p.source_id, "profile_id": p.profile_id,
                "profile_version": p.profile_version, "scope_version": p.scope_version,
                "database": p.database, "tables": list(p.tables),
                "engine_version": p.engine_version, "connector_version": p.connector_version,
                "connector_artifact": p.connector_artifact,
                "transport_version": p.transport_version, "target_version": p.target_version,
                "topology": p.topology, "server_uuid": p.server_uuid,
                "source_server_id": p.source_server_id,
                "connector_server_id": p.connector_server_id, "lineage_mode": p.lineage_mode,
                "max_age_seconds": p.max_age_seconds,
                "minimum_retention_seconds": p.minimum_retention_seconds,
                "maximum_binlog_bytes": p.maximum_binlog_bytes,
                "maximum_binlog_files": p.maximum_binlog_files}

    def _authority(self, authority):
        if (set(authority) != set(AUTHORITY_KEYS)
                or authority.get("source_id") != self.spec.source_id
                or any(type(authority.get(k)) is not int or authority[k] <= 0 for k in (
                    "owner_epoch", "capture_generation", "control_revision", "credential_revision"))
                or not authority.get("binding_id") or not authority.get("runtime_instance_id")):
            raise RuntimeBlocked("mysql_authority_mismatch")
        return dict(authority)

    def inspect(self, connection, *, authority, saved_position):
        authority = self._authority(authority)
        p = self.spec
        observed_at = utc_now().isoformat()
        items = {}

        def item(key, expected, observed, passed=None, owner="DBA"):
            items[key] = {"key": key, "result": (
                "unknown" if passed is None else "pass" if passed else "fail"),
                "expected": expected, "observed": observed, "observed_at": observed_at,
                "owner": owner, "action": "Verify the pinned MySQL profile before admission"}

        variables = {}
        try:
            params = {f"v{i}": v for i, v in enumerate(VARIABLES)}
            names = ", ".join(":" + k for k in params)
            rows = connection.execute(text(
                "SELECT VARIABLE_NAME, VARIABLE_VALUE FROM performance_schema.global_variables "
                f"WHERE VARIABLE_NAME IN ({names})"), params).mappings().all()
            variables = {row["VARIABLE_NAME"].lower(): row["VARIABLE_VALUE"] for row in rows}
        except Exception:
            pass
        for key, variable, expected in (
            ("engine_version", "version", p.engine_version),
            ("binlog_enabled", "log_bin", "ON"),
            ("row_format", "binlog_format", "ROW"),
            ("full_row_image", "binlog_row_image", "FULL"),
        ):
            value = variables.get(variable)
            item(key, expected, value, None if value is None else value == expected)
        item("topology", "single_primary", p.topology,
             None if p.topology == "unknown" else p.topology == "single_primary")
        identity = {"server_uuid": variables.get("server_uuid"),
                    "server_id": variables.get("server_id")}
        item("server_identity", {"server_uuid": p.server_uuid, "server_id": p.source_server_id},
             identity, None if None in identity.values() else (
                 identity["server_uuid"] == p.server_uuid
                 and str(identity["server_id"]) == str(p.source_server_id)))
        scope_ok = None
        try:
            scope_ok = connection.execute(text(
                "SELECT COUNT(*) FROM information_schema.SCHEMATA "
                "WHERE BINARY SCHEMA_NAME = BINARY :database"),
                {"database": p.database}).scalar() == 1
            for table in p.tables:
                exists = connection.execute(text(
                    "SELECT COUNT(*) FROM information_schema.TABLES "
                    "WHERE BINARY TABLE_SCHEMA = BINARY :database "
                    "AND BINARY TABLE_NAME = BINARY :table AND TABLE_TYPE = 'BASE TABLE'"),
                    {"database": p.database, "table": table}).scalar() == 1
                scope_ok = scope_ok and exists
                quote = connection.dialect.identifier_preparer.quote_identifier
                connection.execute(text(f"SELECT * FROM {quote(p.database)}.{quote(table)} LIMIT 0"))
        except Exception:
            scope_ok = None
        item("scope", "Existing readable base tables in the exact database", scope_ok, scope_ok)
        rights = None
        try:
            privileges = set(connection.execute(text(
                "SELECT PRIVILEGE_TYPE FROM information_schema.USER_PRIVILEGES "
                "WHERE GRANTEE = CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(), '@', 1)), "
                "'@', QUOTE(SUBSTRING_INDEX(CURRENT_USER(), '@', -1)))"
            )).scalars().all())
            rights = {"REPLICATION SLAVE", "REPLICATION CLIENT"}.issubset(privileges)
        except Exception:
            pass
        # Role-derived rights are deliberately not guessed from a missing direct grant.
        item("privileges", "Direct replication grants and proven table SELECT", rights,
             True if rights and scope_ok else None)
        logs = None
        try:
            rows = connection.execute(text("SHOW BINARY LOGS")).mappings().fetchmany(
                p.maximum_binlog_files + 1)

            if len(rows) <= p.maximum_binlog_files:
                logs = {r["Log_name"]: int(r["File_size"]) for r in rows}
            else:
                item("binlog_capacity", p.maximum_binlog_files, len(rows), False)
        except Exception:
            pass
        if "binlog_capacity" not in items:
            total = None if logs is None else sum(logs.values())
            item("binlog_capacity", p.maximum_binlog_bytes, total,
                 None if total is None else bool(logs) and 0 <= total < p.maximum_binlog_bytes)
        retained = variables.get("binlog_expire_logs_seconds")
        try:
            retention_ok = int(retained) >= p.minimum_retention_seconds
        except (ValueError, TypeError):
            retention_ok = None
        item("retention", {"minimum_seconds": p.minimum_retention_seconds}, retained, retention_ok)
        valid = None
        if isinstance(saved_position, dict) and variables.get("gtid_mode") is not None:
            if saved_position.get("server_uuid") != p.server_uuid:
                valid = False
            elif p.lineage_mode == "file" and logs is not None:
                position = saved_position.get("position")
                valid = (variables["gtid_mode"] == "OFF"
                         and saved_position.get("file") in logs
                         and type(position) is int
                         and 4 <= position <= logs.get(saved_position.get("file"), 0))
            elif p.lineage_mode == "gtid" and variables["gtid_mode"] == "ON":
                gtid = saved_position.get("gtid_set")
                if isinstance(gtid, str) and gtid:
                    try:
                        valid = connection.execute(text(
                            "SELECT GTID_SUBSET(:saved, @@GLOBAL.gtid_executed) "
                            "AND GTID_SUBSET(@@GLOBAL.gtid_purged, :saved)"),
                            {"saved": gtid}).scalar() == 1
                    except Exception:
                        pass
        item("lineage", "Saved position retained on the pinned server and GTID mode", valid, valid)
        for key in sorted(INDEPENDENT_CHECKS):
            item(key, "Fresh independently resolved scope-bound proof", None, owner="deployer")
            if self.proof_resolver is not None:
                try:
                    proof = self.proof_resolver(key, scope=self.scope(), authority=authority)
                    if (proof["scope"] == self.scope() and proof["authority"] == authority
                            and proof["verified"] is True
                            and proof.get("result") in {"pass", "fail", "unknown"}
                            and isinstance(proof.get("ref"), str)
                            and re.fullmatch(r"sha256:[0-9a-f]{64}", proof["ref"])
                            and self._fresh(proof["observed_at"])):
                        items[key].update(result=proof["result"], observed=proof["ref"],
                                          observed_at=proof["observed_at"])
                except Exception:
                    pass
        return {**self.scope(), "authority": authority, "observed_at": observed_at,
                "readiness": list(items.values())}

    def connector_config(self, report, *, authority, host, port, topic_prefix,
                         history_topic, history_bootstrap_servers, history_security_refs):
        """Generate a private candidate config; the manager owns installation/dispatch.

        FileConfigProvider must be installed by the deployer. Files are installed
        privately by the secret adapter for this binding and credential revision.
        No arbitrary connector overrides or plaintext credentials are accepted.
        """
        self.require_admission(report, authority=authority)
        binding = authority["binding_id"]
        if (not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", binding)
                or not isinstance(host, str) or not re.fullmatch(r"[A-Za-z0-9.-]+", host)
                or type(port) is not int or not 0 < port < 65536
                or topic_prefix != f"refraq.{binding}.g{authority['capture_generation']}"
                or history_topic != topic_prefix + ".schema"
                or not isinstance(history_bootstrap_servers, str)
                or not re.fullmatch(r"[A-Za-z0-9.-]+:[0-9]{1,5}(?:,[A-Za-z0-9.-]+:[0-9]{1,5})*",
                                    history_bootstrap_servers)
                or history_security_refs != {
                    "ssl.truststore.location": "truststore",
                    "ssl.truststore.password": "truststore_password",
                    "ssl.keystore.location": "keystore",
                    "ssl.keystore.password": "keystore_password",
                    "ssl.key.password": "key_password"}):
            raise RuntimeBlocked("mysql_connector_not_allowlisted")
        revision = authority["credential_revision"]
        base = f"/run/refraq/capture/{binding}/"

        def ref(file, key):
            return "${file:" + base + f"{file}-r{revision}.properties:" + key + "}"

        p = self.spec
        config = {
            "connector.class": "io.debezium.connector.mysql.MySqlConnector",
            "tasks.max": "1", "database.hostname": host, "database.port": str(port),
            "database.user": ref("credentials", "username"),
            "database.password": ref("credentials", "password"),
            "database.server.id": str(p.connector_server_id),
            "database.include.list": re.escape(p.database),
            "table.include.list": ",".join(re.escape(p.database + "." + t) for t in p.tables),
            "topic.prefix": topic_prefix, "database.ssl.mode": "verify_identity",
            "snapshot.mode": "no_data", "snapshot.locking.mode": "none",
            "signal.enabled.channels": "kafka", "signal.kafka.topic": topic_prefix + ".signal",
            "signal.kafka.bootstrap.servers": history_bootstrap_servers,
            "schema.history.internal.kafka.bootstrap.servers": history_bootstrap_servers,
            "schema.history.internal.kafka.topic": history_topic,
            "include.schema.changes": "true", "tombstones.on.delete": "true",
            "decimal.handling.mode": "precise", "bigint.unsigned.handling.mode": "precise",
            "time.precision.mode": "adaptive_time_microseconds", "binary.handling.mode": "bytes",
            "database.ssl.keystore": ref("credentials", "keystore"),
            "database.ssl.keystore.password": ref("credentials", "keystore_password"),
            "database.ssl.truststore": ref("credentials", "truststore"),
            "database.ssl.truststore.password": ref("credentials", "truststore_password"),
        }
        for prefix in ("schema.history.internal.producer.", "schema.history.internal.consumer.",
                       "signal.consumer."):
            config[prefix + "security.protocol"] = "SSL"
            config[prefix + "ssl.endpoint.identification.algorithm"] = "https"
            for key, value in history_security_refs.items():
                config[prefix + key] = ref("transport", value)
        return config

    def _fresh(self, value):
        try:
            instant = datetime.fromisoformat(value)
            return instant.tzinfo is not None and 0 <= (utc_now() - instant).total_seconds() <= self.spec.max_age_seconds
        except (ValueError, TypeError):
            return False

    def require_admission(self, report, *, authority):
        self._authority(authority)
        if (any(report.get(k) != v for k, v in self.scope().items())
                or report.get("authority") != authority):
            raise RuntimeBlocked("mysql_observation_scope_mismatch")
        items = report.get("readiness", [])
        expected = SQL_CHECKS | INDEPENDENT_CHECKS
        if (not self._fresh(report.get("observed_at"))
                or len(items) != len(expected)
                or {i.get("key") for i in items} != expected
                or any(i.get("result") != "pass" or not self._fresh(i.get("observed_at")) for i in items)):
            raise RuntimeBlocked("mysql_readiness_unknown_or_failed")
