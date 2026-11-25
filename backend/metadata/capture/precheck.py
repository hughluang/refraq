"""Advisory Capture Precheck. Reads system catalogs and does not admit capture."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from backend.core.secrets import decrypt_secret
from backend.metadata.capture.observations import (
    MSSQL_AGENT_SQL,
    MSSQL_CDC_SQL,
    MSSQL_EDITION_SQL,
    MSSQL_RETENTION_SQL,
    MSSQL_SELECT_SQL,
    MSSQL_VERSION_SQL,
    MSSQL_VIEW_SERVER_SQL,
    ORACLE_ARCHIVE_SQL,
    ORACLE_LOGGING_SQL,
    ORACLE_MINING_PRIVILEGES,
    ORACLE_RETENTION_SQL,
    ORACLE_SUPPLEMENTAL_SQL,
    ORACLE_VERSION_SQL,
    PG_SERVER_SQL,
    mssql_instance,
    mysql_privilege_set,
    mysql_select_probe,
    mysql_variables,
    oracle_privileges,
    oracle_select_probe,
    pg_column_coverage_failed,
    read_outcome,
)
from backend.metadata.connectors.base import ConnectorError
from backend.metadata.connectors.runtime import prepare, run_bounded
from backend.metadata.errors import SourceEngineUnsupported

PRECHECK_TIMEOUT_SECONDS = 10
TABLE_LIMIT = 200
_RESULT_ORDER = {"fail": 0, "unknown": 1, "pass": 2}
_MSSQL_IDENT = re.compile(r"[A-Za-z0-9_$#@]{1,128}")
_MYSQL_IDENT = re.compile(r"[A-Za-z0-9_$]{1,64}")
_ORACLE_IDENT = re.compile(r"[A-Z][A-Z0-9_$#]{0,127}")
_PERMISSION_ITEMS = {
    "mssql": frozenset({"view_server_state", "cdc_jobs_readable"}),
    "postgresql": frozenset({"replication_role"}),
    "mysql": frozenset({"privileges"}),
    "oracle": frozenset({"privileges"}),
}
_FAILED = "Capture precheck could not read the source"
_MSSQL_TABLES_SQL = (
    "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
    "WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA = :schema ORDER BY TABLE_NAME"
)
_MYSQL_TABLES_SQL = (
    "SELECT TABLE_NAME FROM information_schema.TABLES WHERE BINARY TABLE_SCHEMA = BINARY :database "
    "AND TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME"
)
_ORACLE_TABLES_SQL = "SELECT table_name FROM all_tables WHERE owner = :owner ORDER BY table_name"
_PG_PUBLICATIONS_SQL = (
    "SELECT DISTINCT published.pubname FROM pg_catalog.pg_publication_tables AS published "
    "WHERE published.schemaname = :schema ORDER BY published.pubname"
)
_PG_SCHEMA_TABLES_SQL = """
    SELECT relation.relname,
           published.pubname,
           published.rowfilter IS NOT NULL,
           published.attnames,
           attributes.names,
           attributes.has_generated,
           has_table_privilege(relation.oid, 'SELECT')
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    LEFT JOIN pg_catalog.pg_publication_tables AS published
      ON published.schemaname = namespace.nspname AND published.tablename = relation.relname
    CROSS JOIN LATERAL (
        SELECT array_agg(attname) AS names, bool_or(attgenerated <> '') AS has_generated
        FROM pg_catalog.pg_attribute
        WHERE attrelid = relation.oid AND attnum > 0 AND NOT attisdropped
    ) AS attributes
    WHERE namespace.nspname = :schema
      AND relation.relkind = 'r' AND relation.relpersistence = 'p'
    ORDER BY relation.relname, published.pubname
"""


@dataclass
class PrecheckResult:
    ok: bool
    code: str | None = None
    message: str | None = None
    credential: str | None = None
    engine: str | None = None
    items: list[dict[str, Any]] | None = None
    tables: dict[str, Any] | None = None

    def public(self) -> dict[str, Any]:
        if not self.ok:
            return {"ok": False, "code": self.code, "message": self.message}
        return {
            "ok": True,
            "advisory": True,
            "credential": self.credential,
            "engine": self.engine,
            "items": self.items,
            "tables": self.tables,
        }


def resolve_capture_login(
    *,
    request_username: str | None,
    request_password: str | None,
    stored_ciphertext: str | None,
    access: dict[str, Any],
) -> tuple[str, str, str]:
    """First available login: request capture, stored capture, then ordinary access."""
    if request_username is not None:
        return request_username, request_password or "", "request"
    stored = _stored_login(stored_ciphertext)
    if stored is not None:
        return stored[0], stored[1], "stored"
    return str(access["username"]), str(access["password"]), "access"


def run_capture_precheck(
    *,
    engine: str,
    access: dict[str, Any],
    credential_override: tuple[str, str] | None = None,
    credential: str = "access",
) -> PrecheckResult:
    """Inspect one endpoint. ``credential_override`` replaces the access login for this call only."""
    if credential_override is None:
        username, password, credential = str(access["username"]), str(access["password"]), "access"
    else:
        username, password = credential_override
    try:
        prepared = prepare(engine=engine, access=access)
    except ConnectorError as exc:
        raise SourceEngineUnsupported() from exc
    endpoint = replace(prepared.endpoint, username=username, password=password)

    def _run() -> tuple[list[dict[str, Any]], dict[str, Any]]:
        with prepared.connector.inspection_connection(endpoint) as connection:
            return inspect_capture(engine, connection, access, credential)

    try:
        items, tables = run_bounded(_run, timeout_sec=PRECHECK_TIMEOUT_SECONDS)
    except TimeoutError:
        return PrecheckResult(
            ok=False,
            code="SOURCE_CAPTURE_CHECK_TIMEOUT",
            message=f"Capture precheck timed out after {PRECHECK_TIMEOUT_SECONDS}s",
        )
    except Exception:
        return PrecheckResult(ok=False, code="SOURCE_CAPTURE_CHECK_FAILED", message=_FAILED)
    return PrecheckResult(
        ok=True, credential=credential, engine=engine, items=items, tables=tables,
    )


def inspect_capture(engine: str, connection: object, access: dict[str, Any], credential: str):
    """Source and table items from an open connection. Does not open or close it."""
    items, tables = _INSPECTORS[engine](connection, access)
    if tables is None:
        items.append(item("table_list", "unknown"))
        tables = {"total": 0, "truncated": False, "limit": TABLE_LIMIT, "items": []}
    if credential == "access":
        for entry in items:
            if entry["key"] in _PERMISSION_ITEMS[engine]:
                entry["note"] = "access_credential"
        for entry in tables["items"]:
            entry["note"] = "access_credential"
    return items, tables


def mssql_edition_result(edition: str | None) -> str:
    """Express and Web cannot host CDC. Other recognized editions pass; the rest stay unknown."""
    if not isinstance(edition, str) or not edition.strip():
        return "unknown"
    text = edition.lower()
    if "express" in text or re.search(r"\bweb\b", text):
        return "fail"
    if any(token in text for token in (
            "standard", "developer", "enterprise", "evaluation", "business intelligence")):
        return "pass"
    return "unknown"


def item(key, result, *, expected=None, observed=None, action=None):
    if result in {"pass", "not_applicable"}:
        action = None
    elif result == "unknown" and action is None:
        action = "unobserved"
    return {
        "key": key,
        "result": result,
        "expected": expected,
        "observed": None if observed is None else str(observed),
        "action": action,
        "note": None,
    }


def _table(name, result, cause=None, observed=None):
    return {
        "name": name,
        "result": result,
        "cause": cause,
        "observed": None if observed is None else str(observed),
        "note": None,
    }


def _envelope(items, total):
    return {
        "total": total,
        "truncated": total > TABLE_LIMIT,
        "limit": TABLE_LIMIT,
        "items": sorted(items, key=lambda entry: (_RESULT_ORDER[entry["result"]], entry["name"])),
    }


def _limit(names):
    ordered = sorted(name for name in names if isinstance(name, str))
    return ordered[:TABLE_LIMIT], len(ordered)


def _stored_login(ciphertext: str | None):
    if not ciphertext:
        return None
    try:
        data = json.loads(decrypt_secret(ciphertext))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    username, password = data.get("username"), data.get("password")
    if (not isinstance(username, str) or not username
            or not isinstance(password, str) or not password):
        return None
    return username, password


def _number_text(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, str):
        try:
            float(value)
        except ValueError:
            return None
        return value
    return None


def _as_bool(value):
    if value in (True, 1, "1"):
        return True
    if value in (False, 0, "0"):
        return False
    return None


def _observed(key, value):
    if value is None:
        return item(key, "unknown")
    return item(key, "not_applicable", observed=value)


def _status(key, value, expected, action):
    if value is None:
        return item(key, "unknown")
    if value == expected:
        return item(key, "pass", expected=expected, observed=value)
    return item(key, "fail", expected=expected, observed=value, action=action)


def _bit_item(key, value, expected, action):
    parsed = _as_bool(value)
    if parsed is None:
        return item(key, "unknown")
    if parsed:
        return item(key, "pass", expected=expected, observed="1")
    return item(key, "fail", expected=expected, observed="0", action=action)


def _retention(value, readable, missing_action):
    if not readable:
        return item("retention", "unknown")
    if value is None:
        return item("retention", "fail", action=missing_action)
    number = _number_text(value)
    if number is None:
        return item("retention", "unknown", observed=value)
    return item("retention", "not_applicable", observed=number)


def _inspect_mssql(connection, access):
    version, _version_ok = read_outcome(connection, MSSQL_VERSION_SQL)
    edition = read_outcome(connection, MSSQL_EDITION_SQL)[0]
    enabled, _enabled_ok = read_outcome(connection, MSSQL_CDC_SQL)
    agent, _agent_ok = read_outcome(connection, MSSQL_AGENT_SQL)
    minutes, retention_ok = read_outcome(connection, MSSQL_RETENTION_SQL)
    view_state, _view_ok = read_outcome(connection, MSSQL_VIEW_SERVER_SQL)
    edition_state = mssql_edition_result(edition)
    items = [
        _observed("engine_version", version),
        item(
            "edition",
            edition_state,
            observed=edition,
            action="edition_unsupported" if edition_state == "fail" else None,
        ),
        _status("agent_running", agent, "Running", "start_sql_agent"),
        _bit_item("cdc_enabled", enabled, "enabled", "enable_database_cdc"),
        _retention(minutes, retention_ok, "retention_missing"),
        _bit_item("view_server_state", view_state, "1", "grant_view_server_state"),
        item("cdc_jobs_readable", "pass" if retention_ok else "unknown", action="grant_cdc_jobs"),
    ]
    return items, _mssql_tables(connection, str(access.get("schema") or ""))


def _mssql_tables(connection, schema):
    try:
        names = connection.execute(text(_MSSQL_TABLES_SQL), {"schema": schema}).scalars().all()
    except Exception:
        return None
    chosen, total = _limit(names)
    items = []
    for name in chosen:
        qualified = f"{schema}.{name}"
        if _MSSQL_IDENT.fullmatch(schema) is None or _MSSQL_IDENT.fullmatch(name) is None:
            items.append(_table(qualified, "unknown", observed="name_rejected"))
            continue
        try:
            instances, live, captured = mssql_instance(connection, qualified)
            readable = connection.execute(text(MSSQL_SELECT_SQL), {"table": qualified}).scalar()
        except Exception:
            items.append(_table(qualified, "unknown"))
            continue
        if not live or len(instances) != 1 or captured != live:
            items.append(_table(qualified, "fail", "schema", f"instances={len(instances)}"))
            continue
        if readable != 1:
            items.append(_table(qualified, "fail", "permission", "select=0"))
            continue
        items.append(_table(qualified, "pass", observed="instances=1"))
    return _envelope(items, total)


def _inspect_postgresql(connection, access):
    schema = str(access.get("schema") or "")
    try:
        row = connection.execute(text(PG_SERVER_SQL)).fetchone()
    except Exception:
        row = None
    if not row or len(tuple(row)) != 5:
        wal = version = replication = superuser = None
    else:
        _database, wal, version, replication, superuser = tuple(row)
    items = [
        _status("wal_level", wal, "logical", "set_wal_level"),
        _replication(replication, superuser),
        _observed("engine_version", version),
        _publications(connection, schema),
    ]
    return items, _postgresql_tables(connection, schema)


def _replication(replication, superuser):
    if replication is None or superuser is None:
        return item("replication_role", "unknown")
    if superuser:
        return item("replication_role", "fail", expected="replication", observed="superuser",
                    action="reject_superuser")
    if not replication:
        return item("replication_role", "fail", expected="replication", observed="missing",
                    action="grant_replication")
    return item("replication_role", "pass", expected="replication", observed="replication")


def _publications(connection, schema):
    try:
        names = [str(name) for name in connection.execute(
            text(_PG_PUBLICATIONS_SQL), {"schema": schema}).scalars().all() if name]
    except Exception:
        return item("publications", "unknown")
    if not names:
        return item("publications", "fail", expected="publication", action="create_publication")
    observed = ", ".join(names[:20])
    if len(names) > 20:
        observed += ", ..."
    return item("publications", "pass", observed=observed)


def _postgresql_tables(connection, schema):
    try:
        rows = connection.execute(text(_PG_SCHEMA_TABLES_SQL), {"schema": schema}).all()
    except Exception:
        return None
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(str(row[0]), []).append(row)
    names = sorted(grouped)
    items = []
    for name in names[:TABLE_LIMIT]:
        qualified = f"{schema}.{name}"
        entries = grouped[name]
        published = [entry for entry in entries if entry[1] is not None]
        if not published:
            items.append(_table(qualified, "fail", "schema", "unpublished"))
            continue
        covered = any(
            not pg_column_coverage_failed(entry[2], entry[3], entry[4], entry[5])
            for entry in published
        )
        if not covered:
            items.append(_table(qualified, "fail", "schema", "columns_differ"))
            continue
        readable = entries[0][6]
        if readable is True:
            items.append(_table(qualified, "pass"))
        elif readable is False:
            items.append(_table(qualified, "fail", "permission", "select=0"))
        else:
            items.append(_table(qualified, "unknown"))
    return _envelope(items, len(names))


def _inspect_mysql(connection, access):
    database = str(access.get("database") or "")
    variables = mysql_variables(connection)
    items = [
        _observed("engine_version", variables.get("version")),
        _status("binlog_enabled", variables.get("log_bin"), "ON", "enable_binlog"),
        _status("row_format", variables.get("binlog_format"), "ROW", "set_row_format"),
        _status("full_row_image", variables.get("binlog_row_image"), "FULL", "set_full_row_image"),
        _observed("lineage_mode", variables.get("gtid_mode")),
        _retention(variables.get("binlog_expire_logs_seconds"), "binlog_expire_logs_seconds" in variables,
                   "retention_missing"),
        _mysql_privileges(connection),
    ]
    return items, _mysql_tables(connection, database)


def _mysql_privileges(connection):
    granted = mysql_privilege_set(connection)
    expected = "REPLICATION SLAVE, REPLICATION CLIENT"
    if granted is None:
        return item("privileges", "unknown", action="grant_replication_privileges")
    if {"REPLICATION SLAVE", "REPLICATION CLIENT"} <= granted:
        return item("privileges", "pass", expected=expected)
    return item("privileges", "fail", expected=expected, observed="missing",
                action="grant_replication_privileges")


def _mysql_tables(connection, database):
    try:
        names = connection.execute(text(_MYSQL_TABLES_SQL), {"database": database}).scalars().all()
    except Exception:
        return None
    chosen, total = _limit(names)
    items = []
    safe_database = _MYSQL_IDENT.fullmatch(database) is not None
    for name in chosen:
        qualified = f"{database}.{name}"
        if not safe_database or _MYSQL_IDENT.fullmatch(name) is None:
            items.append(_table(qualified, "unknown", observed="name_rejected"))
            continue
        try:
            mysql_select_probe(connection, database, name)
        except Exception:
            items.append(_table(qualified, "fail", "permission", "select=0"))
            continue
        items.append(_table(qualified, "pass"))
    return _envelope(items, total)


def _inspect_oracle(connection, access):
    owner = str(access.get("owner") or "")
    version, _ok = read_outcome(connection, ORACLE_VERSION_SQL)
    mode, _ok = read_outcome(connection, ORACLE_ARCHIVE_SQL)
    minimal, _ok = read_outcome(connection, ORACLE_SUPPLEMENTAL_SQL)
    seconds, retention_ok = read_outcome(connection, ORACLE_RETENTION_SQL)
    items = [
        _observed("engine_version", version),
        _status("archivelog", mode, "ARCHIVELOG", "enable_archivelog"),
        _supplemental(minimal),
        _retention(seconds, retention_ok, "retention_missing"),
        _oracle_privileges(connection),
    ]
    return items, _oracle_tables(connection, owner)


def _supplemental(minimal):
    if minimal is None:
        return item("supplemental_logging", "unknown")
    if minimal in {"YES", "IMPLICIT"}:
        return item("supplemental_logging", "pass", expected="YES", observed=minimal)
    return item("supplemental_logging", "fail", expected="YES", observed=minimal,
                action="enable_supplemental_logging")


def _oracle_privileges(connection):
    granted = oracle_privileges(connection)
    expected = "CREATE SESSION, LOGMINING, SELECT ANY TRANSACTION"
    if granted is None:
        return item("privileges", "unknown", action="grant_mining")
    if ORACLE_MINING_PRIVILEGES <= granted:
        return item("privileges", "pass", expected=expected)
    missing = ", ".join(sorted(ORACLE_MINING_PRIVILEGES - granted))
    return item("privileges", "fail", expected=expected, observed=missing, action="grant_mining")


def _oracle_tables(connection, owner):
    try:
        names = connection.execute(text(_ORACLE_TABLES_SQL), {"owner": owner}).scalars().all()
    except Exception:
        return None
    chosen, total = _limit(names)
    safe_owner = _ORACLE_IDENT.fullmatch(owner) is not None
    items = []
    for name in chosen:
        qualified = f"{owner}.{name}"
        if not safe_owner or _ORACLE_IDENT.fullmatch(name) is None:
            items.append(_table(qualified, "unknown", observed="name_rejected"))
            continue
        try:
            logging = connection.execute(
                text(ORACLE_LOGGING_SQL), {"owner": owner, "name": name}).scalar()
        except Exception:
            items.append(_table(qualified, "unknown"))
            continue
        if not logging:
            items.append(_table(qualified, "fail", "schema", "supplemental_logging=0"))
            continue
        try:
            oracle_select_probe(connection, owner, name)
        except Exception:
            items.append(_table(qualified, "fail", "permission", "select=0"))
            continue
        items.append(_table(qualified, "pass"))
    return _envelope(items, total)


_INSPECTORS = {
    "mssql": _inspect_mssql,
    "postgresql": _inspect_postgresql,
    "mysql": _inspect_mysql,
    "oracle": _inspect_oracle,
}
