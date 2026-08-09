"""PostgreSQL structure connector via pg_catalog."""

from __future__ import annotations

from urllib.parse import quote_plus

from sqlalchemy import create_engine, text

from backend.metadata.connectors.base import (
    CollectedColumn,
    CollectedObject,
    CollectedStructure,
    QueryResult,
    SourceEndpoint,
    ConnectorError,
    fetch_query_result,
    query_endpoint_error,
)

SYSTEM_SCHEMAS = frozenset({"pg_catalog", "information_schema", "pg_toast"})


class PostgresqlConnector:
    engine = "postgresql"

    def test_connection(self, endpoint: SourceEndpoint) -> None:
        eng = self._engine(endpoint)
        try:
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 — map driver errors
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
        eng = self._engine(endpoint)
        try:
            with eng.connect() as conn:
                timeout_ms = max(1, int(timeout_sec) * 1000)
                conn.execute(text(f"SET LOCAL statement_timeout = {timeout_ms}"))
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
                    schema_clause = "AND n.nspname = :schema_filter"
                    params["schema_filter"] = endpoint.schema_filter

                obj_sql = text(
                    f"""
                    SELECT
                      n.nspname AS schema_name,
                      c.relname AS name,
                      CASE c.relkind
                        WHEN 'r' THEN 'table'
                        WHEN 'p' THEN 'table'
                        WHEN 'v' THEN 'view'
                        WHEN 'm' THEN 'view'
                        ELSE c.relkind::text
                      END AS object_type,
                      c.oid AS oid
                    FROM pg_catalog.pg_class c
                    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.relkind IN ('r', 'p', 'v', 'm')
                      AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
                      AND n.nspname NOT LIKE 'pg_toast%%'
                      AND n.nspname NOT LIKE 'pg_temp%%'
                      {schema_clause}
                    ORDER BY n.nspname, c.relname
                    """
                )
                rows = conn.execute(obj_sql, params).mappings().all()
                objects: list[CollectedObject] = []
                for row in rows:
                    if row["object_type"] not in {"table", "view"}:
                        continue
                    cols = self._columns(conn, int(row["oid"]))
                    ddl = None
                    if row["object_type"] == "view":
                        ddl = self._view_ddl(conn, row["schema_name"], row["name"])
                    objects.append(
                        CollectedObject(
                            schema_name=row["schema_name"],
                            name=row["name"],
                            object_type=row["object_type"],
                            columns=cols,
                            ddl=ddl,
                        )
                    )
                return CollectedStructure(objects=objects)
        except ConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError("JOB_COLLECT_FAILED", str(exc)) from exc
        finally:
            eng.dispose()

    def _columns(self, conn: object, oid: int) -> list[CollectedColumn]:
        sql = text(
            """
            SELECT
              a.attname AS name,
              a.attnum AS ordinal,
              pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
              NOT a.attnotnull AS nullable
            FROM pg_catalog.pg_attribute a
            WHERE a.attrelid = :oid
              AND a.attnum > 0
              AND NOT a.attisdropped
            ORDER BY a.attnum
            """
        )
        rows = conn.execute(sql, {"oid": oid}).mappings().all()  # type: ignore[attr-defined]
        return [
            CollectedColumn(
                name=r["name"],
                ordinal=int(r["ordinal"]),
                data_type=r["data_type"],
                nullable=bool(r["nullable"]),
            )
            for r in rows
        ]

    def _view_ddl(self, conn: object, schema: str, name: str) -> str | None:
        try:
            sql = text(
                """
                SELECT pg_catalog.pg_get_viewdef(
                  (quote_ident(:schema) || '.' || quote_ident(:name))::regclass,
                  true
                ) AS ddl
                """
            )
            row = conn.execute(sql, {"schema": schema, "name": name}).mappings().first()  # type: ignore[attr-defined]
            if row and row["ddl"]:
                return f"CREATE OR REPLACE VIEW {schema}.{name} AS\n{row['ddl']}"
        except Exception:  # noqa: BLE001 — ddl optional
            return None
        return None

    def _engine(self, endpoint: SourceEndpoint):
        from backend.metadata.connectors.tls import postgres_connect_args, tls_temp_files

        user = quote_plus(endpoint.username)
        password = quote_plus(endpoint.password)
        db = quote_plus(endpoint.database_name)
        url = (
            f"postgresql+psycopg://{user}:{password}"
            f"@{endpoint.host}:{endpoint.port}/{db}"
        )
        tls_cm = tls_temp_files(endpoint)
        paths = tls_cm.__enter__()
        connect_args = postgres_connect_args(endpoint, paths)
        eng = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
        original_dispose = eng.dispose

        def dispose(*args, **kwargs):  # noqa: ANN002, ANN003
            try:
                return original_dispose(*args, **kwargs)
            finally:
                tls_cm.__exit__(None, None, None)

        eng.dispose = dispose  # type: ignore[method-assign]
        return eng
