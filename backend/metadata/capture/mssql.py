"""Pinned SQL Server CDC capture profile; never runs ``sp_cdc_enable_*`` or changes capture instances.

Capture reads the CDC change tables the DBA enabled. The profile observes that CDC
is enabled for the database and for exactly one capture instance per table covering
every live column, that the Agent cleanup job retains enough history, and that the
capture identity can read each table. Unobservable items stay unknown and block.
It is not qualification of any SQL Server version, edition or topology.
"""

import re

from sqlalchemy import URL, create_engine, text
from sqlalchemy.pool import NullPool

from backend.metadata.capture.observations import (
    MSSQL_AGENT_SQL, MSSQL_CDC_SQL, MSSQL_RETENTION_SQL, MSSQL_SELECT_SQL, MSSQL_VERSION_SQL,
    mssql_instance, read_outcome,
)
from backend.metadata.capture.profile_support import CaptureProfileBase, disposed
from backend.metadata.capture.runtime_store import RuntimeBlocked

_IDENT = r"[A-Za-z0-9_$#@]{1,128}"
_SIGNAL_COLUMNS = ["id", "type", "data"]


def _connect(*, host, port, database, username, password, tls, timeout):
    engine = create_engine(
        URL.create("mssql+pymssql", username=username, password=password, host=host, port=port, database=database),
        connect_args={"login_timeout": timeout, "timeout": timeout, "tds_version": "7.4", "encryption": "require"},
        poolclass=NullPool, hide_parameters=True,
    )
    return disposed(engine)


class MSSQLCaptureProfile(CaptureProfileBase):
    engine_code = "mssql"
    prerequisites = ("engine_version", "cdc_enabled", "agent_running", "retention")
    extra_scope = frozenset({"minimum_retention_seconds"})
    table_pattern = re.compile(rf"{_IDENT}\.{_IDENT}")
    default_connect = staticmethod(_connect)

    def _validate_engine_scope(self):
        p = self.scope
        if (type(p["minimum_retention_seconds"]) is not int or p["minimum_retention_seconds"] <= 0
                or not re.fullmatch(_IDENT, p["database"])
                or len({t.split(".")[0] for t in self.included_tables}) != 1):
            raise RuntimeBlocked("explicit_mssql_profile_required")

    def collection_id(self, qualified_table):
        return f'{self.scope["database"]}.{qualified_table}'

    def _access_matches(self, access):
        p = self.scope
        schema = self.scope["tables"][0].split(".")[0]
        return all(access.get(k) == p[k] for k in ("host", "port", "database")) and access.get("schema") == schema

    def _inspect(self, connection):
        p = self.scope
        results, failures = {}, []

        version = read_outcome(connection, MSSQL_VERSION_SQL)[0]
        results["engine_version"] = version == p["server_version"]
        enabled = read_outcome(connection, MSSQL_CDC_SQL)[0]
        results["cdc_enabled"] = bool(enabled)
        agent = read_outcome(connection, MSSQL_AGENT_SQL)[0]
        results["agent_running"] = agent == "Running"
        minutes = read_outcome(connection, MSSQL_RETENTION_SQL)[0]
        results["retention"] = minutes is not None and int(minutes) * 60 >= p["minimum_retention_seconds"]
        for table in p["tables"]:
            failure = self._table(connection, table)
            if failure is not None:
                failures.append((table, failure))
        if self.snapshot is not None:
            results["signal_relation"] = self._signal(connection)
        return results, failures

    def _table(self, connection, table):
        instances, live, captured = mssql_instance(connection, table)
        readable = connection.execute(text(MSSQL_SELECT_SQL), {"table": table}).scalar()
        if not live or len(instances) != 1 or captured != live:
            return "schema"
        return None if readable == 1 else "permission"

    def _signal(self, connection):
        table = self.snapshot["signal_table"]
        try:
            instances, live, captured = mssql_instance(connection, table)
            columns = connection.execute(text(
                "SELECT c.name FROM sys.columns c WHERE c.object_id = OBJECT_ID(:table) ORDER BY c.column_id"),
                {"table": table}).scalars().all()
            textual = connection.execute(text(
                "SELECT COUNT(*) FROM sys.columns c JOIN sys.types t ON t.user_type_id = c.user_type_id "
                "WHERE c.object_id = OBJECT_ID(:table) AND t.name IN ('varchar', 'nvarchar')"),
                {"table": table}).scalar()
            primary = connection.execute(text(
                "SELECT STRING_AGG(c.name, ',') FROM sys.indexes i JOIN sys.index_columns ic "
                "ON ic.object_id = i.object_id AND ic.index_id = i.index_id JOIN sys.columns c "
                "ON c.object_id = ic.object_id AND c.column_id = ic.column_id "
                "WHERE i.object_id = OBJECT_ID(:table) AND i.is_primary_key = 1"), {"table": table}).scalar()
            rights = connection.execute(text(
                "SELECT HAS_PERMS_BY_NAME(:table, 'OBJECT', 'SELECT') + HAS_PERMS_BY_NAME(:table, 'OBJECT', 'INSERT')"),
                {"table": table}).scalar()
            identity = connection.execute(text(
                "SELECT CAST(DB_ID() AS varchar(20)) + ':' + CAST(OBJECT_ID(:table) AS varchar(20))"),
                {"table": table}).scalar()
        except Exception:
            return False
        return (list(columns) == _SIGNAL_COLUMNS and textual == 3 and primary == "id" and rights == 2
                and len(instances) == 1 and captured == live
                and identity == self.snapshot["signal_relation_identity"])

    def _connector(self, tables):
        p, tls = self.scope, self.tls
        return {
            "connector.class": "io.debezium.connector.sqlserver.SqlServerConnector",
            "database.names": p["database"],
            "table.include.list": ",".join(re.escape(t) for t in tables),
            "driver.encrypt": "true", "driver.trustServerCertificate": "false",
            "driver.trustStore": tls["truststore"], "driver.trustStorePassword": tls["truststore_password"],
            "time.precision.mode": "adaptive", "binary.handling.mode": "bytes",
        }
