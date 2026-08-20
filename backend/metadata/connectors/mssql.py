"""MSSQL structure connector via sys.* catalog views."""

from __future__ import annotations

from urllib.parse import quote_plus

from sqlalchemy import create_engine, text

from backend.metadata.connectors.base import (
    CollectedStructure,
    CollectProgress,
    QueryResult,
    SourceEndpoint,
    ConnectorError,
    fetch_query_result,
    query_endpoint_error,
)
from backend.metadata.connectors.structure_rows import (
    ColumnRow,
    DefinitionRow,
    ForeignKeyColumnRow,
    IndexColumnRow,
    KeyColumnRow,
    ObjectRow,
    StructureRows,
    assemble,
    stream_mappings,
)

_OBJECT_TYPES = frozenset({"table", "view", "procedure", "function"})


class MssqlConnector:
    engine = "mssql"

    def test_connection(self, endpoint: SourceEndpoint) -> None:
        eng = self._engine(endpoint)
        try:
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError("JOB_ENDPOINT_FAILED", str(exc)) from exc
        finally:
            eng.dispose()

    def run_readonly(
        self,
        endpoint: SourceEndpoint,
        sql: str,
        *,
        max_rows: int,
        timeout_sec: int,
    ) -> QueryResult:
        eng = self._engine(endpoint, timeout_sec=timeout_sec)
        try:
            with eng.connect() as conn:
                result = conn.execute(text(sql))
                return fetch_query_result(result, max_rows=max_rows)
        except Exception as exc:  # noqa: BLE001
            raise query_endpoint_error(exc) from exc
        finally:
            eng.dispose()

    def collect_structure(
        self,
        endpoint: SourceEndpoint,
        progress: CollectProgress | None = None,
    ) -> CollectedStructure:
        if progress is not None:
            progress.listing_objects(endpoint.schema_filter)
        eng = self._engine(endpoint)
        try:
            with eng.connect() as conn:
                params: dict[str, object] = {
                    "schema_filter": endpoint.schema_filter,
                }
                objects = [
                    ObjectRow(
                        object_key=str(int(row["object_id"])),
                        schema_name=row["schema_name"],
                        name=row["name"],
                        object_type=row["object_type"],
                        comment=row["comment"],
                    )
                    for row in stream_mappings(conn, _OBJECT_SQL, params)
                    if row["object_type"] in _OBJECT_TYPES
                ]
                if progress is not None:
                    progress.listed_objects(len(objects))
                return assemble(
                    StructureRows(
                        objects=objects,
                        columns=_column_rows(conn, params),
                        primary_keys=_primary_key_rows(conn, params),
                        foreign_keys=_foreign_key_rows(conn, params),
                        indexes=_index_rows(conn, params),
                        definitions=_definition_rows(conn, params),
                    ),
                    progress=progress,
                )
        except ConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError("JOB_COLLECT_FAILED", str(exc)) from exc
        finally:
            eng.dispose()

    def _engine(self, endpoint: SourceEndpoint, *, timeout_sec: int | None = None):
        mode = endpoint.ssl_mode or "disable"
        if mode != "disable" or endpoint.ssl_root_cert or endpoint.ssl_client_cert or endpoint.ssl_client_key:
            raise ConnectorError(
                "JOB_ENDPOINT_FAILED",
                "MSSQL TLS is not supported in this slice; use ssl_mode=disable",
            )
        # Prefer pymssql URL; requires pymssql installed.
        user = quote_plus(endpoint.username)
        password = quote_plus(endpoint.password)
        db = quote_plus(endpoint.database_name)
        url = (
            f"mssql+pymssql://{user}:{password}"
            f"@{endpoint.host}:{endpoint.port}/{db}"
        )
        connect_args: dict[str, object] = {}
        if timeout_sec is not None:
            # pymssql: query timeout in seconds (not LOCK_TIMEOUT).
            connect_args["timeout"] = max(1, int(timeout_sec))
        return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


_OBJECT_SQL = text(
    """
    SELECT
      s.name AS schema_name,
      o.name AS name,
      CASE o.type
        WHEN 'U' THEN 'table'
        WHEN 'V' THEN 'view'
        WHEN 'P' THEN 'procedure'
        WHEN 'FN' THEN 'function'
        WHEN 'IF' THEN 'function'
        WHEN 'TF' THEN 'function'
        ELSE RTRIM(o.type)
      END AS object_type,
      o.object_id AS object_id,
      CAST(ep.value AS nvarchar(max)) AS comment
    FROM sys.objects o
    JOIN sys.schemas s ON s.schema_id = o.schema_id
    LEFT JOIN sys.extended_properties ep
      ON ep.major_id = o.object_id
     AND ep.minor_id = 0
     AND ep.name = 'MS_Description'
     AND ep.class = 1
    WHERE o.type IN ('U', 'V', 'P', 'FN', 'IF', 'TF')
      AND s.name NOT IN ('sys', 'INFORMATION_SCHEMA')
      AND s.name = :schema_filter
    ORDER BY s.name, o.name
    """
)

_COLUMN_SQL = text(
    """
    SELECT
      c.object_id AS object_key,
      c.name AS name,
      c.column_id AS ordinal,
      CASE
        WHEN t.name IN ('decimal', 'numeric')
          THEN t.name + '(' + CAST(c.precision AS varchar(10))
               + ',' + CAST(c.scale AS varchar(10)) + ')'
        WHEN t.name IN ('varchar', 'nvarchar', 'char', 'nchar', 'binary', 'varbinary')
          THEN t.name + '(' + CASE
            WHEN c.max_length < 0 THEN 'max'
            WHEN t.name LIKE 'n%' THEN CAST(c.max_length / 2 AS varchar(10))
            ELSE CAST(c.max_length AS varchar(10))
          END + ')'
        ELSE t.name
      END AS data_type,
      c.is_nullable AS nullable,
      dc.definition AS default_value,
      CAST(ep.value AS nvarchar(max)) AS comment
    FROM sys.columns c
    JOIN sys.objects o ON o.object_id = c.object_id
    JOIN sys.schemas s ON s.schema_id = o.schema_id
    JOIN sys.types t ON t.user_type_id = c.user_type_id
    LEFT JOIN sys.default_constraints dc
      ON dc.parent_object_id = c.object_id AND dc.parent_column_id = c.column_id
    LEFT JOIN sys.extended_properties ep
      ON ep.major_id = c.object_id
     AND ep.minor_id = c.column_id
     AND ep.name = 'MS_Description'
     AND ep.class = 1
    WHERE o.type IN ('U', 'V')
      AND s.name NOT IN ('sys', 'INFORMATION_SCHEMA')
      AND s.name = :schema_filter
    ORDER BY c.object_id, c.column_id
    """
)

_PRIMARY_KEY_SQL = text(
    """
    SELECT
      i.object_id AS object_key,
      c.name AS name,
      ic.key_ordinal AS ordinal
    FROM sys.indexes i
    JOIN sys.index_columns ic
      ON ic.object_id = i.object_id AND ic.index_id = i.index_id
    JOIN sys.columns c
      ON c.object_id = ic.object_id AND c.column_id = ic.column_id
    JOIN sys.objects o ON o.object_id = i.object_id
    JOIN sys.schemas s ON s.schema_id = o.schema_id
    WHERE i.is_primary_key = 1
      AND o.type IN ('U', 'V')
      AND s.name NOT IN ('sys', 'INFORMATION_SCHEMA')
      AND s.name = :schema_filter
    ORDER BY i.object_id, ic.key_ordinal
    """
)

_FOREIGN_KEY_SQL = text(
    """
    SELECT
      fk.parent_object_id AS object_key,
      fk.name AS constraint_name,
      pc.name AS column_name,
      sch.name AS ref_schema,
      ref.name AS ref_table,
      rc.name AS ref_column,
      fkc.constraint_column_id AS ordinal
    FROM sys.foreign_keys fk
    JOIN sys.foreign_key_columns fkc
      ON fkc.constraint_object_id = fk.object_id
    JOIN sys.columns pc
      ON pc.object_id = fkc.parent_object_id
     AND pc.column_id = fkc.parent_column_id
    JOIN sys.columns rc
      ON rc.object_id = fkc.referenced_object_id
     AND rc.column_id = fkc.referenced_column_id
    JOIN sys.tables ref ON ref.object_id = fk.referenced_object_id
    JOIN sys.schemas sch ON sch.schema_id = ref.schema_id
    JOIN sys.objects o ON o.object_id = fk.parent_object_id
    JOIN sys.schemas ps ON ps.schema_id = o.schema_id
    WHERE o.type IN ('U', 'V')
      AND ps.name NOT IN ('sys', 'INFORMATION_SCHEMA')
      AND ps.name = :schema_filter
    ORDER BY fk.parent_object_id, fk.name, fkc.constraint_column_id
    """
)

_INDEX_SQL = text(
    """
    SELECT
      i.object_id AS object_key,
      i.name AS index_name,
      c.name AS column_name,
      ic.key_ordinal AS ordinal,
      i.is_unique AS is_unique
    FROM sys.indexes i
    JOIN sys.index_columns ic
      ON ic.object_id = i.object_id AND ic.index_id = i.index_id
    JOIN sys.columns c
      ON c.object_id = ic.object_id AND c.column_id = ic.column_id
    JOIN sys.objects o ON o.object_id = i.object_id
    JOIN sys.schemas s ON s.schema_id = o.schema_id
    WHERE i.is_primary_key = 0
      AND i.name IS NOT NULL
      AND i.type > 0
      AND ic.is_included_column = 0
      AND o.type IN ('U', 'V')
      AND s.name NOT IN ('sys', 'INFORMATION_SCHEMA')
      AND s.name = :schema_filter
    ORDER BY i.object_id, i.name, ic.key_ordinal
    """
)

_DEFINITION_SQL = text(
    """
    SELECT
      m.object_id AS object_key,
      m.definition AS ddl
    FROM sys.sql_modules m
    JOIN sys.objects o ON o.object_id = m.object_id
    JOIN sys.schemas s ON s.schema_id = o.schema_id
    WHERE o.type IN ('V', 'P', 'FN', 'IF', 'TF')
      AND s.name NOT IN ('sys', 'INFORMATION_SCHEMA')
      AND s.name = :schema_filter
    """
)


def _column_rows(conn: object, params: dict[str, object]):
    for row in stream_mappings(conn, _COLUMN_SQL, params):
        yield ColumnRow(
            object_key=str(int(row["object_key"])),
            name=row["name"],
            ordinal=int(row["ordinal"]),
            data_type=str(row["data_type"]),
            nullable=bool(row["nullable"]),
            default_value=row["default_value"],
            comment=row["comment"],
        )


def _primary_key_rows(conn: object, params: dict[str, object]):
    for row in stream_mappings(conn, _PRIMARY_KEY_SQL, params):
        yield KeyColumnRow(
            object_key=str(int(row["object_key"])),
            name=row["name"],
            ordinal=int(row["ordinal"]),
        )


def _foreign_key_rows(conn: object, params: dict[str, object]):
    for row in stream_mappings(conn, _FOREIGN_KEY_SQL, params):
        yield ForeignKeyColumnRow(
            object_key=str(int(row["object_key"])),
            constraint_name=row["constraint_name"],
            column_name=row["column_name"],
            ref_schema=row["ref_schema"],
            ref_table=row["ref_table"],
            ref_column=row["ref_column"],
            ordinal=int(row["ordinal"]),
        )


def _index_rows(conn: object, params: dict[str, object]):
    for row in stream_mappings(conn, _INDEX_SQL, params):
        yield IndexColumnRow(
            object_key=str(int(row["object_key"])),
            index_name=row["index_name"],
            column_name=row["column_name"],
            ordinal=int(row["ordinal"]),
            is_unique=bool(row["is_unique"]),
        )


def _definition_rows(conn: object, params: dict[str, object]):
    try:
        for row in stream_mappings(conn, _DEFINITION_SQL, params):
            ddl = str(row["ddl"]) if row["ddl"] else None
            yield DefinitionRow(object_key=str(int(row["object_key"])), ddl=ddl)
    except Exception:  # noqa: BLE001 — ddl optional
        return
