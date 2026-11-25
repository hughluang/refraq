"""Pinned MySQL binlog capture profile; no automatic grants, signal tables or binlog changes.

The profile observes the capture identity's own view of the server. Independent
safety proofs (alarm drill, owner exclusion, target fence, publication barrier)
arrive through the signed gateway observations that every engine shares, not
through this profile. This profile is not qualification of any MySQL version or topology.
"""

import re

from sqlalchemy import URL, create_engine, text
from sqlalchemy.pool import NullPool

from backend.metadata.capture.observations import (
    mysql_privilege_set, mysql_select_probe, mysql_variables,
)
from backend.metadata.capture.profile_support import CaptureProfileBase, disposed
from backend.metadata.capture.runtime_store import RuntimeBlocked

_SIGNAL_COLUMNS = ["id", "type", "data"]
_TABLE_SQL = (
    "SELECT COUNT(*) FROM information_schema.TABLES WHERE BINARY TABLE_SCHEMA = BINARY :database "
    "AND BINARY TABLE_NAME = BINARY :table AND TABLE_TYPE = 'BASE TABLE'"
)


def _connect(*, host, port, database, username, password, tls, timeout):
    engine = create_engine(
        URL.create("mysql+pymysql", username=username, password=password, host=host, port=port, database=database),
        connect_args={"charset": "utf8mb4", "connect_timeout": timeout, "read_timeout": timeout,
                      "write_timeout": timeout, "local_infile": False,
                      "ssl": {"ca": tls["ca_file"], "check_hostname": True}},
        poolclass=NullPool, hide_parameters=True,
    )
    return disposed(engine)


class MySQLCaptureProfile(CaptureProfileBase):
    engine_code = "mysql"
    prerequisites = (
        "engine_version", "binlog_enabled", "row_format", "full_row_image", "server_identity",
        "retention", "lineage_mode", "privileges", "binlog_capacity",
    )
    extra_scope = frozenset({
        "server_uuid", "source_server_id", "connector_server_id", "lineage_mode",
        "minimum_retention_seconds", "maximum_binlog_bytes", "maximum_binlog_files",
    })
    table_pattern = re.compile(r"[A-Za-z0-9_$]{1,64}\.[A-Za-z0-9_$]{1,64}")
    default_connect = staticmethod(_connect)

    def _validate_engine_scope(self):
        p = self.scope
        numbers = (p["source_server_id"], p["connector_server_id"], p["minimum_retention_seconds"],
                   p["maximum_binlog_bytes"], p["maximum_binlog_files"])
        if (any(type(v) is not int or v <= 0 for v in numbers)
                or not 0 < p["connector_server_id"] < 2**32
                or p["source_server_id"] == p["connector_server_id"]
                or p["lineage_mode"] not in {"file", "gtid"}
                or not re.fullmatch(r"[0-9a-fA-F-]{36}", p["server_uuid"])
                or any(t.split(".")[0] != p["database"] for t in self.included_tables)):
            raise RuntimeBlocked("explicit_mysql_profile_required")

    def _access_matches(self, access):
        p = self.scope
        return all(access.get(k) == p[k] for k in ("host", "port", "database"))

    def _inspect(self, connection):
        p = self.scope
        results, failures = {}, []
        variables = mysql_variables(connection)
        for key, variable, expected in (("engine_version", "version", p["server_version"]),
                                        ("binlog_enabled", "log_bin", "ON"),
                                        ("row_format", "binlog_format", "ROW"),
                                        ("full_row_image", "binlog_row_image", "FULL")):
            results[key] = variables.get(variable) == expected
        results["server_identity"] = (variables.get("server_uuid") == p["server_uuid"]
                                      and str(variables.get("server_id")) == str(p["source_server_id"]))
        try:
            results["retention"] = int(variables.get("binlog_expire_logs_seconds")) >= p["minimum_retention_seconds"]
        except (ValueError, TypeError):
            results["retention"] = False
        results["lineage_mode"] = variables.get("gtid_mode") == ("ON" if p["lineage_mode"] == "gtid" else "OFF")
        results["privileges"] = self._privileges(connection)
        results["binlog_capacity"] = self._capacity(connection)
        for table in p["tables"]:
            failure = self._table(connection, table)
            if failure is not None:
                failures.append((table, failure))
        if self.snapshot is not None:
            results["signal_relation"] = self._signal(connection)
        return results, failures

    @staticmethod
    def _privileges(connection):
        granted = mysql_privilege_set(connection)
        # Role-derived rights are deliberately not guessed from a missing direct grant.
        return granted is not None and {"REPLICATION SLAVE", "REPLICATION CLIENT"} <= granted

    def _capacity(self, connection):
        p = self.scope
        try:
            rows = connection.execute(text("SHOW BINARY LOGS")).mappings().fetchmany(
                p["maximum_binlog_files"] + 1)
        except Exception:
            return False
        if not rows or len(rows) > p["maximum_binlog_files"]:
            return False
        return sum(int(row["File_size"]) for row in rows) < p["maximum_binlog_bytes"]

    @staticmethod
    def _table(connection, table):
        """Return ``schema`` or ``permission`` when this table is observed failing; ``None`` when proven."""
        database, name = table.split(".")
        exists = connection.execute(
            text(_TABLE_SQL), {"database": database, "table": name}).scalar()
        if exists != 1:
            return "schema"
        try:
            mysql_select_probe(connection, database, name)
        except Exception:
            return "permission"
        return None

    def _signal(self, connection):
        database, name = self.snapshot["signal_table"].split(".")
        try:
            columns = connection.execute(text(
                "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE BINARY TABLE_SCHEMA = BINARY :database "
                "AND BINARY TABLE_NAME = BINARY :table ORDER BY ORDINAL_POSITION"),
                {"database": database, "table": name}).scalars().all()
            created = connection.execute(text(
                "SELECT UNIX_TIMESTAMP(CREATE_TIME) FROM information_schema.TABLES WHERE BINARY TABLE_SCHEMA = BINARY :database "
                "AND BINARY TABLE_NAME = BINARY :table AND TABLE_TYPE = 'BASE TABLE'"),
                {"database": database, "table": name}).scalar()
            primary = connection.execute(text(
                "SELECT GROUP_CONCAT(COLUMN_NAME) FROM information_schema.KEY_COLUMN_USAGE "
                "WHERE BINARY TABLE_SCHEMA = BINARY :database AND BINARY TABLE_NAME = BINARY :table "
                "AND CONSTRAINT_NAME = 'PRIMARY'"), {"database": database, "table": name}).scalar()
            grantee = ("CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(), '@', 1)), "
                       "'@', QUOTE(SUBSTRING_INDEX(CURRENT_USER(), '@', -1)))")
            insert = connection.execute(text(
                "SELECT (SELECT COUNT(*) FROM information_schema.USER_PRIVILEGES "
                f"WHERE PRIVILEGE_TYPE = 'INSERT' AND GRANTEE = {grantee}) + "
                "(SELECT COUNT(*) FROM information_schema.TABLE_PRIVILEGES WHERE PRIVILEGE_TYPE = 'INSERT' "
                f"AND GRANTEE = {grantee} AND BINARY TABLE_SCHEMA = BINARY :database "
                "AND BINARY TABLE_NAME = BINARY :table)"), {"database": database, "table": name}).scalar()
            mysql_select_probe(connection, database, name)
        except Exception:
            return False
        # Role-derived INSERT rights are not guessed; an absent direct grant is not proven.
        return (created is not None and insert != 0 and list(columns) == _SIGNAL_COLUMNS and primary == "id"
                and self.snapshot["signal_relation_identity"] == f"{database}.{name}:{int(created)}")

    def _connector(self, tables):
        p, tls = self.scope, self.tls
        config = {
            "connector.class": "io.debezium.connector.mysql.MySqlConnector",
            "database.server.id": str(p["connector_server_id"]),
            "database.include.list": re.escape(p["database"]),
            "table.include.list": ",".join(re.escape(t) for t in tables),
            "database.ssl.mode": "verify_identity",
            "database.ssl.truststore": tls["truststore"],
            "database.ssl.truststore.password": tls["truststore_password"],
            "snapshot.locking.mode": "none",
            "bigint.unsigned.handling.mode": "precise",
            "time.precision.mode": "adaptive_time_microseconds", "binary.handling.mode": "bytes",
        }
        return config
