"""Oracle structure connector via ALL_*/DBA_* views."""

from __future__ import annotations

import os
from urllib.parse import quote_plus

import oracledb
from sqlalchemy import create_engine, text

from backend.metadata.connectors.base import (
    CollectedColumn,
    CollectedForeignKey,
    CollectedIndex,
    CollectedObject,
    CollectedStructure,
    CollectProgress,
    ConnectorError,
    QueryResult,
    SourceEndpoint,
    fetch_query_result,
    query_endpoint_error,
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
                obj_sql = text(
                    """
                    SELECT
                      owner AS schema_name,
                      table_name AS name,
                      'table' AS object_type
                    FROM all_tables
                    WHERE owner = :owner
                    UNION ALL
                    SELECT
                      owner AS schema_name,
                      view_name AS name,
                      'view' AS object_type
                    FROM all_views
                    WHERE owner = :owner
                    UNION ALL
                    SELECT
                      owner AS schema_name,
                      mview_name AS name,
                      'materialized_view' AS object_type
                    FROM all_mviews
                    WHERE owner = :owner
                    ORDER BY 1, 2
                    """
                )
                rows = conn.execute(obj_sql, params).mappings().all()
                total = len(rows)
                if progress is not None:
                    progress.listed_objects(total)
                objects: list[CollectedObject] = []
                for index, row in enumerate(rows, start=1):
                    schema = row["schema_name"]
                    name = row["name"]
                    object_type = row["object_type"]
                    ddl = None
                    if object_type in {"view", "materialized_view"}:
                        ddl = self._view_ddl(conn, schema, name, object_type)
                    objects.append(
                        CollectedObject(
                            schema_name=schema,
                            name=name,
                            object_type=object_type,
                            columns=self._columns(conn, schema, name),
                            ddl=ddl,
                            comment=self._table_comment(conn, schema, name),
                            primary_key=self._primary_key(conn, schema, name),
                            foreign_keys=self._foreign_keys(conn, schema, name),
                            indexes=self._indexes(conn, schema, name),
                        )
                    )
                    if progress is not None:
                        progress.object_done(index, total)
                return CollectedStructure(objects=objects)
        except ConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError("JOB_COLLECT_FAILED", str(exc)) from exc
        finally:
            eng.dispose()

    def _columns(
        self, conn: object, owner: str, table_name: str
    ) -> list[CollectedColumn]:
        sql = text(
            """
            SELECT
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
              cc.comments AS comment
            FROM all_tab_columns c
            LEFT JOIN all_col_comments cc
              ON cc.owner = c.owner
             AND cc.table_name = c.table_name
             AND cc.column_name = c.column_name
            WHERE c.owner = :owner AND c.table_name = :table_name
            ORDER BY c.column_id
            """
        )
        rows = conn.execute(  # type: ignore[attr-defined]
            sql, {"owner": owner, "table_name": table_name}
        ).mappings().all()
        return [
            CollectedColumn(
                name=r["name"],
                ordinal=int(r["ordinal"] or 0),
                data_type=str(r["data_type"]),
                nullable=bool(r["nullable"]),
                default_value=(
                    str(r["default_value"]).strip()
                    if r["default_value"] is not None
                    else None
                ),
                comment=r["comment"],
            )
            for r in rows
        ]

    def _table_comment(self, conn: object, owner: str, table_name: str) -> str | None:
        sql = text(
            """
            SELECT comments
            FROM all_tab_comments
            WHERE owner = :owner AND table_name = :table_name
            """
        )
        row = conn.execute(  # type: ignore[attr-defined]
            sql, {"owner": owner, "table_name": table_name}
        ).mappings().first()
        if row and row["comments"]:
            return str(row["comments"])
        return None

    def _primary_key(self, conn: object, owner: str, table_name: str) -> list[str]:
        sql = text(
            """
            SELECT cols.column_name AS name
            FROM all_constraints cons
            JOIN all_cons_columns cols
              ON cons.owner = cols.owner
             AND cons.constraint_name = cols.constraint_name
            WHERE cons.owner = :owner
              AND cons.table_name = :table_name
              AND cons.constraint_type = 'P'
            ORDER BY cols.position
            """
        )
        rows = conn.execute(  # type: ignore[attr-defined]
            sql, {"owner": owner, "table_name": table_name}
        ).mappings().all()
        return [r["name"] for r in rows]

    def _foreign_keys(
        self, conn: object, owner: str, table_name: str
    ) -> list[CollectedForeignKey]:
        sql = text(
            """
            SELECT
              cons.constraint_name AS name,
              r_cons.owner AS ref_schema,
              r_cons.table_name AS ref_table
            FROM all_constraints cons
            JOIN all_constraints r_cons
              ON cons.r_owner = r_cons.owner
             AND cons.r_constraint_name = r_cons.constraint_name
            WHERE cons.owner = :owner
              AND cons.table_name = :table_name
              AND cons.constraint_type = 'R'
            ORDER BY cons.constraint_name
            """
        )
        rows = conn.execute(  # type: ignore[attr-defined]
            sql, {"owner": owner, "table_name": table_name}
        ).mappings().all()
        out: list[CollectedForeignKey] = []
        for r in rows:
            cols_sql = text(
                """
                SELECT
                  local_cols.column_name AS col_name,
                  ref_cols.column_name AS ref_name,
                  local_cols.position AS ord
                FROM all_cons_columns local_cols
                JOIN all_constraints cons
                  ON cons.owner = local_cols.owner
                 AND cons.constraint_name = local_cols.constraint_name
                JOIN all_cons_columns ref_cols
                  ON ref_cols.owner = cons.r_owner
                 AND ref_cols.constraint_name = cons.r_constraint_name
                 AND ref_cols.position = local_cols.position
                WHERE local_cols.owner = :owner
                  AND local_cols.constraint_name = :cname
                ORDER BY local_cols.position
                """
            )
            col_rows = conn.execute(  # type: ignore[attr-defined]
                cols_sql, {"owner": owner, "cname": r["name"]}
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

    def _indexes(
        self, conn: object, owner: str, table_name: str
    ) -> list[CollectedIndex]:
        sql = text(
            """
            SELECT
              i.index_name AS name,
              CASE i.uniqueness WHEN 'UNIQUE' THEN 1 ELSE 0 END AS is_unique
            FROM all_indexes i
            WHERE i.table_owner = :owner
              AND i.table_name = :table_name
              AND i.index_type != 'LOB'
              AND NOT EXISTS (
                SELECT 1
                FROM all_constraints c
                WHERE c.owner = i.owner
                  AND c.index_name = i.index_name
                  AND c.constraint_type = 'P'
              )
            ORDER BY i.index_name
            """
        )
        rows = conn.execute(  # type: ignore[attr-defined]
            sql, {"owner": owner, "table_name": table_name}
        ).mappings().all()
        out: list[CollectedIndex] = []
        for r in rows:
            cols_sql = text(
                """
                SELECT column_name AS name
                FROM all_ind_columns
                WHERE index_owner = :owner AND index_name = :iname
                ORDER BY column_position
                """
            )
            col_rows = conn.execute(  # type: ignore[attr-defined]
                cols_sql, {"owner": owner, "iname": r["name"]}
            ).mappings().all()
            out.append(
                CollectedIndex(
                    name=r["name"],
                    columns=[c["name"] for c in col_rows],
                    is_unique=bool(r["is_unique"]),
                )
            )
        return out

    def _view_ddl(
        self, conn: object, owner: str, name: str, object_type: str
    ) -> str | None:
        # Prefer DBMS_METADATA; fall back to ALL_VIEWS.TEXT for ordinary views.
        try:
            ddl_type = "MATERIALIZED_VIEW" if object_type == "materialized_view" else "VIEW"
            sql = text(
                """
                SELECT dbms_metadata.get_ddl(:ddl_type, :name, :owner) AS ddl
                FROM dual
                """
            )
            row = conn.execute(  # type: ignore[attr-defined]
                sql, {"ddl_type": ddl_type, "name": name, "owner": owner}
            ).mappings().first()
            if row and row["ddl"]:
                return str(row["ddl"])
        except Exception:  # noqa: BLE001 — optional path
            pass
        if object_type == "view":
            try:
                sql = text(
                    """
                    SELECT text AS ddl
                    FROM all_views
                    WHERE owner = :owner AND view_name = :name
                    """
                )
                row = conn.execute(  # type: ignore[attr-defined]
                    sql, {"owner": owner, "name": name}
                ).mappings().first()
                if row and row["ddl"]:
                    return f"CREATE OR REPLACE VIEW {owner}.{name} AS\n{row['ddl']}"
            except Exception:  # noqa: BLE001
                return None
        return None

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
