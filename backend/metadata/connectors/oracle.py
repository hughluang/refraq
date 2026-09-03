"""Oracle structure connector via ALL_*/DBA_* views."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote_plus

import oracledb
from sqlalchemy import create_engine, text

from backend.metadata.connectors.base import (
    CollectedStructure,
    CollectProgress,
    ConnectorError,
    QueryResult,
    SourceEndpoint,
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


class OracleConnector:
    engine = "oracle"

    def test_connection(self, endpoint: SourceEndpoint) -> None:
        eng = self._engine(endpoint)
        try:
            with eng.connect() as conn:
                conn.execute(text("SELECT 1 FROM DUAL"))
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
        owner_filter = endpoint.schema_filter.upper()
        if progress is not None:
            progress.listing_objects(owner_filter)
        eng = self._engine(endpoint)
        try:
            with eng.connect() as conn:
                params: dict[str, object] = {"owner": owner_filter}
                objects = [
                    ObjectRow(
                        object_key=_object_key(
                            row["schema_name"], row["name"], row["object_type"]
                        ),
                        schema_name=row["schema_name"],
                        name=row["name"],
                        object_type=row["object_type"],
                        comment=row["comment"],
                    )
                    for row in stream_mappings(conn, _OBJECT_SQL, params)
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
                "Oracle TLS is not supported in this slice; use ssl_mode=disable",
            )
        # database_name is service name / SID for Oracle Sources.
        user = quote_plus(endpoint.username)
        password = quote_plus(endpoint.password)
        service = quote_plus(endpoint.database_name)
        thick = os.environ.get("REFRAQ_ORACLE_THICK", "").lower() in {
            "1",
            "true",
            "yes",
        }
        if thick:
            try:
                oracledb.init_oracle_client()
            except Exception as exc:  # noqa: BLE001
                raise ConnectorError(
                    "JOB_CONNECTOR_UNAVAILABLE",
                    f"Oracle thick client init failed: {exc}",
                ) from exc
        url = (
            f"oracle+oracledb://{user}:{password}"
            f"@{endpoint.host}:{endpoint.port}/?service_name={service}"
        )
        connect_args: dict[str, object] = {}
        if timeout_sec is not None:
            # oracledb: call_timeout in milliseconds (JDBC setQueryTimeout analogue).
            connect_args["call_timeout"] = max(1, int(timeout_sec) * 1000)
        return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


def _object_key(owner: str, name: str, object_type: str) -> str:
    return f"{object_type}:{owner}.{name}"


def _row_object_key(row: Any) -> str:
    return _object_key(row["schema_name"], row["object_name"], row["object_type"])


_OBJECT_SQL = text(
    """
    SELECT
      t.owner AS schema_name,
      t.table_name AS name,
      'table' AS object_type,
      c.comments AS "comment"
    FROM all_tables t
    LEFT JOIN all_tab_comments c
      ON c.owner = t.owner AND c.table_name = t.table_name
    WHERE t.owner = :owner
    UNION ALL
    SELECT
      v.owner AS schema_name,
      v.view_name AS name,
      'view' AS object_type,
      c.comments AS "comment"
    FROM all_views v
    LEFT JOIN all_tab_comments c
      ON c.owner = v.owner AND c.table_name = v.view_name
    WHERE v.owner = :owner
    UNION ALL
    SELECT
      m.owner AS schema_name,
      m.mview_name AS name,
      'materialized_view' AS object_type,
      c.comments AS "comment"
    FROM all_mviews m
    LEFT JOIN all_tab_comments c
      ON c.owner = m.owner AND c.table_name = m.mview_name
    WHERE m.owner = :owner
    UNION ALL
    SELECT
      o.owner AS schema_name,
      o.object_name AS name,
      'procedure' AS object_type,
      CAST(NULL AS VARCHAR2(4000)) AS "comment"
    FROM all_objects o
    WHERE o.owner = :owner AND o.object_type = 'PROCEDURE'
    UNION ALL
    SELECT
      o.owner AS schema_name,
      o.object_name AS name,
      'function' AS object_type,
      CAST(NULL AS VARCHAR2(4000)) AS "comment"
    FROM all_objects o
    WHERE o.owner = :owner AND o.object_type = 'FUNCTION'
    ORDER BY 1, 2, 3
    """
)

# Same identity set as _OBJECT_SQL (without comments). Detail fetches join this
# so a table and materialized_view that share owner+name each get their own key.
_OBJECT_IDENTITY = """
      SELECT t.owner AS schema_name, t.table_name AS name, 'table' AS object_type
      FROM all_tables t
      WHERE t.owner = :owner
      UNION ALL
      SELECT v.owner, v.view_name, 'view'
      FROM all_views v
      WHERE v.owner = :owner
      UNION ALL
      SELECT m.owner, m.mview_name, 'materialized_view'
      FROM all_mviews m
      WHERE m.owner = :owner
"""

_COLUMN_SQL = text(
    f"""
    SELECT
      o.object_type AS object_type,
      c.owner AS schema_name,
      c.table_name AS object_name,
      c.column_name AS name,
      c.column_id AS ordinal,
      CASE
        WHEN c.data_type IN ('VARCHAR2', 'NVARCHAR2', 'CHAR', 'NCHAR', 'RAW')
          THEN c.data_type || '(' || c.data_length || ')'
        WHEN c.data_type IN ('NUMBER') AND c.data_precision IS NOT NULL
          THEN c.data_type || '(' || c.data_precision
               || CASE
                    WHEN c.data_scale IS NOT NULL
                      THEN ',' || c.data_scale
                    ELSE ''
                  END || ')'
        ELSE c.data_type
      END AS data_type,
      CASE c.nullable WHEN 'Y' THEN 1 ELSE 0 END AS nullable,
      c.data_default AS default_value,
      cc.comments AS "comment"
    FROM all_tab_columns c
    JOIN (
      {_OBJECT_IDENTITY}
    ) o ON o.schema_name = c.owner AND o.name = c.table_name
    LEFT JOIN all_col_comments cc
      ON cc.owner = c.owner
     AND cc.table_name = c.table_name
     AND cc.column_name = c.column_name
    WHERE c.owner = :owner
    ORDER BY c.table_name, o.object_type, c.column_id
    """
)

_PRIMARY_KEY_SQL = text(
    f"""
    SELECT
      o.object_type AS object_type,
      cons.owner AS schema_name,
      cons.table_name AS object_name,
      cols.column_name AS name,
      cols.position AS ordinal
    FROM all_constraints cons
    JOIN all_cons_columns cols
      ON cons.owner = cols.owner
     AND cons.constraint_name = cols.constraint_name
    JOIN (
      {_OBJECT_IDENTITY}
    ) o ON o.schema_name = cons.owner AND o.name = cons.table_name
    WHERE cons.owner = :owner
      AND cons.constraint_type = 'P'
    ORDER BY cons.table_name, o.object_type, cols.position
    """
)

_FOREIGN_KEY_SQL = text(
    f"""
    SELECT
      o.object_type AS object_type,
      cons.owner AS schema_name,
      cons.table_name AS object_name,
      cons.constraint_name AS constraint_name,
      local_cols.column_name AS column_name,
      r_cons.owner AS ref_schema,
      r_cons.table_name AS ref_table,
      ref_cols.column_name AS ref_column,
      local_cols.position AS ordinal
    FROM all_constraints cons
    JOIN all_constraints r_cons
      ON cons.r_owner = r_cons.owner
     AND cons.r_constraint_name = r_cons.constraint_name
    JOIN all_cons_columns local_cols
      ON local_cols.owner = cons.owner
     AND local_cols.constraint_name = cons.constraint_name
    JOIN all_cons_columns ref_cols
      ON ref_cols.owner = cons.r_owner
     AND ref_cols.constraint_name = cons.r_constraint_name
     AND ref_cols.position = local_cols.position
    JOIN (
      {_OBJECT_IDENTITY}
    ) o ON o.schema_name = cons.owner AND o.name = cons.table_name
    WHERE cons.owner = :owner
      AND cons.constraint_type = 'R'
    ORDER BY cons.table_name, o.object_type, cons.constraint_name, local_cols.position
    """
)

_INDEX_SQL = text(
    f"""
    SELECT
      o.object_type AS object_type,
      i.table_owner AS schema_name,
      i.table_name AS object_name,
      i.index_name AS index_name,
      ic.column_name AS column_name,
      ic.column_position AS ordinal,
      CASE i.uniqueness WHEN 'UNIQUE' THEN 1 ELSE 0 END AS is_unique
    FROM all_indexes i
    JOIN all_ind_columns ic
      ON ic.index_owner = i.owner
     AND ic.index_name = i.index_name
    JOIN (
      {_OBJECT_IDENTITY}
    ) o ON o.schema_name = i.table_owner AND o.name = i.table_name
    WHERE i.table_owner = :owner
      AND i.index_type != 'LOB'
      AND NOT EXISTS (
        SELECT 1
        FROM all_constraints c
        WHERE c.owner = i.owner
          AND c.index_name = i.index_name
          AND c.constraint_type = 'P'
      )
    ORDER BY i.table_name, o.object_type, i.index_name, ic.column_position
    """
)

_DEFINITION_SQL = text(
    """
    SELECT
      'view' AS object_type,
      owner AS schema_name,
      view_name AS object_name,
      dbms_metadata.get_ddl('VIEW', view_name, owner) AS ddl
    FROM all_views
    WHERE owner = :owner
    UNION ALL
    SELECT
      'materialized_view' AS object_type,
      owner AS schema_name,
      mview_name AS object_name,
      dbms_metadata.get_ddl('MATERIALIZED_VIEW', mview_name, owner) AS ddl
    FROM all_mviews
    WHERE owner = :owner
    UNION ALL
    SELECT
      'procedure' AS object_type,
      owner AS schema_name,
      object_name AS object_name,
      dbms_metadata.get_ddl('PROCEDURE', object_name, owner) AS ddl
    FROM all_objects
    WHERE owner = :owner AND object_type = 'PROCEDURE'
    UNION ALL
    SELECT
      'function' AS object_type,
      owner AS schema_name,
      object_name AS object_name,
      dbms_metadata.get_ddl('FUNCTION', object_name, owner) AS ddl
    FROM all_objects
    WHERE owner = :owner AND object_type = 'FUNCTION'
    """
)

_DEFINITION_FALLBACK_SQL = text(
    """
    SELECT
      'view' AS object_type,
      owner AS schema_name,
      view_name AS object_name,
      text AS ddl
    FROM all_views
    WHERE owner = :owner
    """
)

_ROUTINE_SOURCE_SQL = text(
    """
    SELECT
      CASE type
        WHEN 'PROCEDURE' THEN 'procedure'
        ELSE 'function'
      END AS object_type,
      owner AS schema_name,
      name AS object_name,
      line AS line_no,
      text AS text
    FROM all_source
    WHERE owner = :owner
      AND type IN ('PROCEDURE', 'FUNCTION')
    ORDER BY name, type, line
    """
)


def _column_rows(conn: object, params: dict[str, object]):
    for row in stream_mappings(conn, _COLUMN_SQL, params):
        yield ColumnRow(
            object_key=_row_object_key(row),
            name=row["name"],
            ordinal=int(row["ordinal"] or 0),
            data_type=str(row["data_type"]),
            nullable=bool(row["nullable"]),
            default_value=(
                str(row["default_value"]).strip()
                if row["default_value"] is not None
                else None
            ),
            comment=row["comment"],
        )


def _primary_key_rows(conn: object, params: dict[str, object]):
    for row in stream_mappings(conn, _PRIMARY_KEY_SQL, params):
        yield KeyColumnRow(
            object_key=_row_object_key(row),
            name=row["name"],
            ordinal=int(row["ordinal"] or 0),
        )


def _foreign_key_rows(conn: object, params: dict[str, object]):
    for row in stream_mappings(conn, _FOREIGN_KEY_SQL, params):
        yield ForeignKeyColumnRow(
            object_key=_row_object_key(row),
            constraint_name=row["constraint_name"],
            column_name=row["column_name"],
            ref_schema=row["ref_schema"],
            ref_table=row["ref_table"],
            ref_column=row["ref_column"],
            ordinal=int(row["ordinal"] or 0),
        )


def _index_rows(conn: object, params: dict[str, object]):
    for row in stream_mappings(conn, _INDEX_SQL, params):
        yield IndexColumnRow(
            object_key=_row_object_key(row),
            index_name=row["index_name"],
            column_name=row["column_name"],
            ordinal=int(row["ordinal"] or 0),
            is_unique=bool(row["is_unique"]),
        )


def _definition_rows(conn: object, params: dict[str, object]):
    try:
        for row in stream_mappings(conn, _DEFINITION_SQL, params):
            ddl = str(row["ddl"]) if row["ddl"] else None
            yield DefinitionRow(object_key=_row_object_key(row), ddl=ddl)
        return
    except Exception:  # noqa: BLE001 — optional path
        pass
    try:
        chunks: dict[str, list[str]] = {}
        for row in stream_mappings(conn, _DEFINITION_FALLBACK_SQL, params):
            if not row["ddl"]:
                yield DefinitionRow(object_key=_row_object_key(row), ddl=None)
                continue
            ddl = (
                f"CREATE OR REPLACE VIEW {row['schema_name']}.{row['object_name']} "
                f"AS\n{row['ddl']}"
            )
            yield DefinitionRow(object_key=_row_object_key(row), ddl=ddl)
        for row in stream_mappings(conn, _ROUTINE_SOURCE_SQL, params):
            key = _row_object_key(row)
            chunks.setdefault(key, []).append(str(row["text"] or ""))
        for object_key, parts in chunks.items():
            body = "".join(parts).strip()
            yield DefinitionRow(object_key=object_key, ddl=body or None)
    except Exception:  # noqa: BLE001
        return
