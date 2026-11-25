"""Catalog observations shared by capture profiles and Capture Precheck.

Profiles judge these facts against a pinned scope. Precheck reports the same
facts and leaves pinned comparisons unjudged. Nothing here creates publications,
CDC instances, supplemental logging, signal tables, or grants.
"""

from sqlalchemy import text

PG_SERVER_SQL = (
    "SELECT current_database(), current_setting('wal_level'), "
    "current_setting('server_version_num')::int, rolreplication, "
    "rolsuper FROM pg_roles WHERE rolname = current_user"
)

MSSQL_VERSION_SQL = "SELECT CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(64))"
MSSQL_EDITION_SQL = "SELECT CAST(SERVERPROPERTY('Edition') AS nvarchar(128))"
MSSQL_CDC_SQL = "SELECT is_cdc_enabled FROM sys.databases WHERE name = DB_NAME()"
MSSQL_AGENT_SQL = (
    "SELECT status_desc FROM sys.dm_server_services WHERE servicename LIKE 'SQL Server Agent%'"
)
MSSQL_RETENTION_SQL = (
    "SELECT MIN(retention) FROM msdb.dbo.cdc_jobs "
    "WHERE database_id = DB_ID() AND job_type = 'cleanup'"
)
MSSQL_VIEW_SERVER_SQL = "SELECT HAS_PERMS_BY_NAME(NULL, NULL, 'VIEW SERVER STATE')"
MSSQL_INSTANCES_SQL = (
    "SELECT capture_instance FROM cdc.change_tables WHERE source_object_id = OBJECT_ID(:table)"
)
MSSQL_LIVE_SQL = "SELECT name FROM sys.columns WHERE object_id = OBJECT_ID(:table)"
MSSQL_CAPTURED_SQL = (
    "SELECT column_name FROM cdc.captured_columns WHERE object_id = "
    "(SELECT object_id FROM cdc.change_tables WHERE capture_instance = :instance)"
)
MSSQL_SELECT_SQL = "SELECT HAS_PERMS_BY_NAME(:table, 'OBJECT', 'SELECT')"

MYSQL_VARIABLES = (
    "version", "log_bin", "binlog_format", "binlog_row_image", "server_uuid",
    "server_id", "gtid_mode", "binlog_expire_logs_seconds",
)
MYSQL_PRIVILEGE_SQL = (
    "SELECT PRIVILEGE_TYPE FROM information_schema.USER_PRIVILEGES "
    "WHERE GRANTEE = CONCAT(QUOTE(SUBSTRING_INDEX(CURRENT_USER(), '@', 1)), "
    "'@', QUOTE(SUBSTRING_INDEX(CURRENT_USER(), '@', -1)))"
)

ORACLE_VERSION_SQL = "SELECT version_full FROM product_component_version WHERE ROWNUM = 1"
ORACLE_ARCHIVE_SQL = "SELECT log_mode FROM v$database"
ORACLE_SUPPLEMENTAL_SQL = "SELECT supplemental_log_data_min FROM v$database"
ORACLE_RETENTION_SQL = (
    "SELECT (SYSDATE - MIN(first_time)) * 86400 FROM v$archived_log WHERE deleted = 'NO'"
)
ORACLE_PRIVILEGE_SQL = "SELECT privilege FROM session_privs"
ORACLE_LOGGING_SQL = (
    "SELECT (SELECT COUNT(*) FROM all_log_groups WHERE owner = :owner AND table_name = :name "
    "AND log_group_type = 'ALL COLUMN LOGGING') + "
    "(SELECT COUNT(*) FROM v$database WHERE supplemental_log_data_all = 'YES') FROM dual"
)
ORACLE_MINING_PRIVILEGES = {"CREATE SESSION", "LOGMINING", "SELECT ANY TRANSACTION"}


def read_outcome(connection, sql, params=None):
    """``(value, True)`` when the statement ran, ``(None, False)`` when it did not."""
    try:
        return connection.execute(text(sql), params or {}).scalar(), True
    except Exception:
        return None, False


def pg_column_coverage_failed(filtered, published_columns, live_columns, has_generated):
    """True when a published table is not the full live column set the profile requires."""
    return (filtered is not False or has_generated is not False
            or not published_columns or not live_columns
            or set(published_columns) != set(live_columns))


def mssql_instance(connection, table):
    """Capture instances and captured/live column sets. Raises when unobservable."""
    instances = connection.execute(text(MSSQL_INSTANCES_SQL), {"table": table}).scalars().all()
    live = set(connection.execute(text(MSSQL_LIVE_SQL), {"table": table}).scalars().all())
    captured = None
    if len(instances) == 1:
        captured = set(connection.execute(
            text(MSSQL_CAPTURED_SQL), {"instance": instances[0]}).scalars().all())
    return instances, live, captured


def mysql_variables(connection):
    try:
        params = {f"v{index}": name for index, name in enumerate(MYSQL_VARIABLES)}
        names = ", ".join(":" + key for key in params)
        rows = connection.execute(text(
            "SELECT VARIABLE_NAME, VARIABLE_VALUE FROM performance_schema.global_variables "
            f"WHERE VARIABLE_NAME IN ({names})"), params).mappings().all()
        return {row["VARIABLE_NAME"].lower(): row["VARIABLE_VALUE"] for row in rows}
    except Exception:
        return {}


def mysql_privilege_set(connection):
    """Direct grants, or ``None`` when the catalog cannot be read. Roles are not guessed."""
    try:
        return set(connection.execute(text(MYSQL_PRIVILEGE_SQL)).scalars().all())
    except Exception:
        return None


def mysql_select_probe(connection, database, name):
    quote = connection.dialect.identifier_preparer.quote_identifier
    connection.execute(text(f"SELECT * FROM {quote(database)}.{quote(name)} LIMIT 0"))


def oracle_privileges(connection):
    try:
        return set(connection.execute(text(ORACLE_PRIVILEGE_SQL)).scalars().all())
    except Exception:
        return None


def oracle_select_probe(connection, owner, name):
    connection.execute(text(f'SELECT 1 FROM "{owner}"."{name}" WHERE 1 = 0'))
