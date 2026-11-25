"""Pinned Oracle LogMiner capture profile; never enables logging, grants or signal tables.

The profile observes that the database runs in ARCHIVELOG mode with minimal
supplemental logging, that each captured table has all-column supplemental
logging, that archived redo covers the approved retention and that the capture
identity holds the mining privileges and can read each table. Unobservable items
stay unknown and block. It is not qualification of any Oracle version or topology.
"""

import re
import ssl

import oracledb
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from backend.metadata.capture.observations import (
    ORACLE_ARCHIVE_SQL, ORACLE_LOGGING_SQL, ORACLE_MINING_PRIVILEGES, ORACLE_RETENTION_SQL,
    ORACLE_SUPPLEMENTAL_SQL, ORACLE_VERSION_SQL, oracle_privileges, oracle_select_probe,
    read_outcome,
)
from backend.metadata.capture.profile_support import CaptureProfileBase, disposed
from backend.metadata.capture.runtime_store import RuntimeBlocked

_IDENT = r"[A-Z][A-Z0-9_$#]{0,127}"
_SIGNAL_COLUMNS = ["ID", "TYPE", "DATA"]
_EXISTS_SQL = "SELECT COUNT(*) FROM all_tables WHERE owner = :owner AND table_name = :name"


def _connect(*, host, port, database, username, password, tls, timeout, service_name):
    context = ssl.create_default_context(cafile=tls["ca_file"])
    engine = create_engine(
        "oracle+oracledb://", poolclass=NullPool, hide_parameters=True,
        creator=lambda: oracledb.connect(
            user=username, password=password, host=host, port=port, service_name=service_name,
            protocol="tcps", ssl_context=context, ssl_server_dn_match=True, tcp_connect_timeout=timeout),
    )
    return disposed(engine)


class OracleCaptureProfile(CaptureProfileBase):
    engine_code = "oracle"
    prerequisites = ("engine_version", "archivelog", "supplemental_logging", "retention", "privileges")
    extra_scope = frozenset({"service_name", "cdb", "minimum_retention_seconds"})
    table_pattern = re.compile(rf"{_IDENT}\.{_IDENT}")
    default_connect = staticmethod(_connect)

    def _validate_engine_scope(self):
        p = self.scope
        if (type(p["minimum_retention_seconds"]) is not int or p["minimum_retention_seconds"] <= 0
                or any(not isinstance(p[k], str) or not re.fullmatch(_IDENT, p[k]) for k in ("database", "cdb"))
                or not isinstance(p["service_name"], str)
                or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", p["service_name"])
                or len({t.split(".")[0] for t in self.included_tables}) != 1):
            raise RuntimeBlocked("explicit_oracle_profile_required")

    def collection_id(self, qualified_table):
        return f'{self.scope["database"]}.{qualified_table}'

    def _connect_options(self):
        return {"service_name": self.scope["service_name"]}

    def _access_matches(self, access):
        p = self.scope
        return (all(access.get(k) == p[k] for k in ("host", "port", "service_name"))
                and access.get("owner") == p["tables"][0].split(".")[0])

    def _inspect(self, connection):
        p = self.scope
        results, failures = {}, []

        version = read_outcome(connection, ORACLE_VERSION_SQL)[0]
        results["engine_version"] = version == p["server_version"]
        mode = read_outcome(connection, ORACLE_ARCHIVE_SQL)[0]
        results["archivelog"] = mode == "ARCHIVELOG"
        minimal = read_outcome(connection, ORACLE_SUPPLEMENTAL_SQL)[0]
        results["supplemental_logging"] = minimal in {"YES", "IMPLICIT"}
        seconds = read_outcome(connection, ORACLE_RETENTION_SQL)[0]
        results["retention"] = seconds is not None and seconds >= p["minimum_retention_seconds"]
        granted = oracle_privileges(connection)
        results["privileges"] = granted is not None and ORACLE_MINING_PRIVILEGES <= granted
        for table in p["tables"]:
            failure = self._table(connection, table)
            if failure is not None:
                failures.append((table, failure))
        if self.snapshot is not None:
            results["signal_relation"] = self._signal(connection)
        return results, failures

    @staticmethod
    def _table(connection, table):
        owner, name = table.split(".")
        key = {"owner": owner, "name": name}
        exists = connection.execute(text(_EXISTS_SQL), key).scalar()
        logging = connection.execute(text(ORACLE_LOGGING_SQL), key).scalar()
        if exists != 1 or not logging:
            return "schema"
        try:
            oracle_select_probe(connection, owner, name)
        except Exception:
            return "permission"
        return None

    def _signal(self, connection):
        owner, name = self.snapshot["signal_table"].split(".")
        key = {"owner": owner, "name": name}
        try:
            columns = connection.execute(text(
                "SELECT column_name FROM all_tab_columns WHERE owner = :owner AND table_name = :name "
                "ORDER BY column_id"), key).scalars().all()
            textual = connection.execute(text(
                "SELECT COUNT(*) FROM all_tab_columns WHERE owner = :owner AND table_name = :name "
                "AND data_type IN ('VARCHAR2', 'NVARCHAR2')"), key).scalar()
            primary = connection.execute(text(
                "SELECT LISTAGG(cc.column_name, ',') WITHIN GROUP (ORDER BY cc.position) FROM all_constraints c "
                "JOIN all_cons_columns cc ON cc.owner = c.owner AND cc.constraint_name = c.constraint_name "
                "WHERE c.owner = :owner AND c.table_name = :name AND c.constraint_type = 'P'"), key).scalar()
            writable = connection.execute(text(
                "SELECT (SELECT COUNT(*) FROM user_users WHERE username = :owner) + "
                "(SELECT COUNT(*) FROM all_tab_privs WHERE table_schema = :owner AND table_name = :name "
                "AND privilege = 'INSERT') FROM dual"), key).scalar()
            logging = connection.execute(text(
                "SELECT (SELECT COUNT(*) FROM all_log_groups WHERE owner = :owner AND table_name = :name "
                "AND log_group_type = 'ALL COLUMN LOGGING') + "
                "(SELECT COUNT(*) FROM v$database WHERE supplemental_log_data_all = 'YES') FROM dual"), key).scalar()
            identity = connection.execute(text(
                "SELECT :container || ':' || object_id FROM all_objects WHERE owner = :owner "
                "AND object_name = :name AND object_type = 'TABLE'"),
                {**key, "container": self.scope["database"]}).scalar()
            connection.execute(text(f'SELECT 1 FROM "{owner}"."{name}" WHERE 1 = 0'))
        except Exception:
            return False
        return (list(columns) == _SIGNAL_COLUMNS and textual == 3 and primary == "ID" and bool(writable)
                and bool(logging) and identity == self.snapshot["signal_relation_identity"])

    def _connector(self, tables):
        p, tls = self.scope, self.tls
        return {
            "connector.class": "io.debezium.connector.oracle.OracleConnector",
            "database.dbname": p["cdb"], "database.pdb.name": p["database"],
            "database.connection.adapter": "logminer", "log.mining.strategy": "online_catalog",
            "table.include.list": ",".join(re.escape(t) for t in tables),
            "driver.javax.net.ssl.trustStore": tls["truststore"],
            "driver.javax.net.ssl.trustStorePassword": tls["truststore_password"],
            "driver.oracle.net.ssl_server_dn_match": "true",
            "database.url": (f'jdbc:oracle:thin:@(DESCRIPTION=(ADDRESS=(PROTOCOL=tcps)(HOST={p["host"]})(PORT={p["port"]}))'
                             f'(CONNECT_DATA=(SERVICE_NAME={p["service_name"]})))'),
            "time.precision.mode": "adaptive", "binary.handling.mode": "bytes",
        }
