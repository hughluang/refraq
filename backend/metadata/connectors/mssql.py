"""MSSQL structure connector via sys.* catalog views."""

from __future__ import annotations

from urllib.parse import quote_plus

from sqlalchemy import create_engine, text

from backend.metadata.connectors.base import (
    CollectedColumn,
    CollectedForeignKey,
    CollectedIndex,
    CollectedObject,
    CollectedStructure,
    QueryResult,
    SourceEndpoint,
    ConnectorError,
    fetch_query_result,
    query_endpoint_error,
)

_OBJECT_TYPES = frozenset({"table", "view"})


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

    def collect_structure(self, endpoint: SourceEndpoint) -> CollectedStructure:
        eng = self._engine(endpoint)
        try:
            with eng.connect() as conn:
                params: dict[str, object] = {}
                schema_clause = ""
                if endpoint.schema_filter:
                    schema_clause = "AND s.name = :schema_filter"
                    params["schema_filter"] = endpoint.schema_filter

                obj_sql = text(
                    f"""
                    SELECT
                      s.name AS schema_name,
                      o.name AS name,
                      CASE o.type
                        WHEN 'U' THEN 'table'
                        WHEN 'V' THEN 'view'
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
                    WHERE o.type IN ('U', 'V')
                      AND s.name NOT IN ('sys', 'INFORMATION_SCHEMA')
                      {schema_clause}
                    ORDER BY s.name, o.name
                    """
                )
                rows = conn.execute(obj_sql, params).mappings().all()
                objects: list[CollectedObject] = []
                for row in rows:
                    if row["object_type"] not in _OBJECT_TYPES:
                        continue
                    object_id = int(row["object_id"])
                    ddl = None
                    if row["object_type"] == "view":
                        ddl = self._view_ddl(conn, object_id)
                    objects.append(
                        CollectedObject(
                            schema_name=row["schema_name"],
                            name=row["name"],
                            object_type=row["object_type"],
                            columns=self._columns(conn, object_id),
                            ddl=ddl,
                            comment=row["comment"],
                            primary_key=self._primary_key(conn, object_id),
                            foreign_keys=self._foreign_keys(conn, object_id),
                            indexes=self._indexes(conn, object_id),
                        )
                    )
                return CollectedStructure(objects=objects)
        except ConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError("JOB_COLLECT_FAILED", str(exc)) from exc
        finally:
            eng.dispose()

    def _columns(self, conn: object, object_id: int) -> list[CollectedColumn]:
        sql = text(
            """
            SELECT
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
            JOIN sys.types t ON t.user_type_id = c.user_type_id
            LEFT JOIN sys.default_constraints dc
              ON dc.parent_object_id = c.object_id AND dc.parent_column_id = c.column_id
            LEFT JOIN sys.extended_properties ep
              ON ep.major_id = c.object_id
             AND ep.minor_id = c.column_id
             AND ep.name = 'MS_Description'
             AND ep.class = 1
            WHERE c.object_id = :object_id
            ORDER BY c.column_id
            """
        )
        rows = conn.execute(sql, {"object_id": object_id}).mappings().all()  # type: ignore[attr-defined]
        return [
            CollectedColumn(
                name=r["name"],
                ordinal=int(r["ordinal"]),
                data_type=str(r["data_type"]),
                nullable=bool(r["nullable"]),
                default_value=r["default_value"],
                comment=r["comment"],
            )
            for r in rows
        ]

    def _primary_key(self, conn: object, object_id: int) -> list[str]:
        sql = text(
            """
            SELECT c.name AS name
            FROM sys.indexes i
            JOIN sys.index_columns ic
              ON ic.object_id = i.object_id AND ic.index_id = i.index_id
            JOIN sys.columns c
              ON c.object_id = ic.object_id AND c.column_id = ic.column_id
            WHERE i.object_id = :object_id AND i.is_primary_key = 1
            ORDER BY ic.key_ordinal
            """
        )
        rows = conn.execute(sql, {"object_id": object_id}).mappings().all()  # type: ignore[attr-defined]
        return [r["name"] for r in rows]

    def _foreign_keys(self, conn: object, object_id: int) -> list[CollectedForeignKey]:
        sql = text(
            """
            SELECT
              fk.name AS name,
              fk.object_id AS fk_id,
              sch.name AS ref_schema,
              ref.name AS ref_table
            FROM sys.foreign_keys fk
            JOIN sys.tables ref ON ref.object_id = fk.referenced_object_id
            JOIN sys.schemas sch ON sch.schema_id = ref.schema_id
            WHERE fk.parent_object_id = :object_id
            ORDER BY fk.name
            """
        )
        rows = conn.execute(sql, {"object_id": object_id}).mappings().all()  # type: ignore[attr-defined]
        out: list[CollectedForeignKey] = []
        for r in rows:
            cols_sql = text(
                """
                SELECT
                  pc.name AS col_name,
                  rc.name AS ref_name,
                  fkc.constraint_column_id AS ord
                FROM sys.foreign_key_columns fkc
                JOIN sys.columns pc
                  ON pc.object_id = fkc.parent_object_id
                 AND pc.column_id = fkc.parent_column_id
                JOIN sys.columns rc
                  ON rc.object_id = fkc.referenced_object_id
                 AND rc.column_id = fkc.referenced_column_id
                WHERE fkc.constraint_object_id = :fk_id
                ORDER BY fkc.constraint_column_id
                """
            )
            col_rows = conn.execute(  # type: ignore[attr-defined]
                cols_sql, {"fk_id": int(r["fk_id"])}
            ).mappings().all()
            out.append(
                CollectedForeignKey(
                    name=r["name"],
                    columns=[c["col_name"] for c in col_rows],
                    ref_schema=r["ref_schema"],
                    ref_table=r["ref_table"],
                    ref_columns=[c["ref_name"] for c in col_rows],
                )
            )
        return out

    def _indexes(self, conn: object, object_id: int) -> list[CollectedIndex]:
        sql = text(
            """
            SELECT
              i.name AS name,
              i.is_unique AS is_unique,
              i.index_id AS index_id
            FROM sys.indexes i
            WHERE i.object_id = :object_id
              AND i.is_primary_key = 0
              AND i.name IS NOT NULL
              AND i.type > 0
            ORDER BY i.name
            """
        )
        rows = conn.execute(sql, {"object_id": object_id}).mappings().all()  # type: ignore[attr-defined]
        out: list[CollectedIndex] = []
        for r in rows:
            cols_sql = text(
                """
                SELECT c.name AS name
                FROM sys.index_columns ic
                JOIN sys.columns c
                  ON c.object_id = ic.object_id AND c.column_id = ic.column_id
                WHERE ic.object_id = :object_id
                  AND ic.index_id = :index_id
                  AND ic.is_included_column = 0
                ORDER BY ic.key_ordinal
                """
            )
            col_rows = conn.execute(  # type: ignore[attr-defined]
                cols_sql,
                {"object_id": object_id, "index_id": int(r["index_id"])},
            ).mappings().all()
            out.append(
                CollectedIndex(
                    name=r["name"],
                    columns=[c["name"] for c in col_rows],
                    is_unique=bool(r["is_unique"]),
                )
            )
        return out

    def _view_ddl(self, conn: object, object_id: int) -> str | None:
        try:
            sql = text(
                """
                SELECT m.definition AS ddl
                FROM sys.sql_modules m
                WHERE m.object_id = :object_id
                """
            )
            row = conn.execute(sql, {"object_id": object_id}).mappings().first()  # type: ignore[attr-defined]
            if row and row["ddl"]:
                return str(row["ddl"])
        except Exception:  # noqa: BLE001 — ddl optional
            return None
        return None

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
