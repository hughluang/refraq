"""PostgreSQL structure connector via pg_catalog."""

from __future__ import annotations

from urllib.parse import quote_plus

from psycopg.adapt import Loader
from psycopg.types import TypeInfo
from sqlalchemy import create_engine, event, text

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

SYSTEM_SCHEMAS = frozenset({"pg_catalog", "information_schema", "pg_toast"})

# Connector contract: pool connections load int2vector as list[int] so
# _indexes can iterate attnums without treating the text wire form as a str.
# psycopg3 has no built-in loader; without this, indkey arrives as "1 2" and
# `for n in indkey` yields spaces → JOB_COLLECT_FAILED.


class Int2VectorLoader(Loader):
    """Load PostgreSQL int2vector text wire format into list[int]."""

    def load(self, data: bytes | bytearray | memoryview) -> list[int]:
        if not data:
            return []
        raw = data.tobytes() if isinstance(data, memoryview) else data
        return [int(n) for n in raw.decode("utf-8").split()]


def register_int2vector_loader(conn: object) -> None:
    """Register Int2VectorLoader on a psycopg DBAPI connection."""
    info = TypeInfo.fetch(conn, "int2vector")  # type: ignore[arg-type]
    if info is None:
        raise ConnectorError(
            "JOB_ENDPOINT_FAILED",
            "PostgreSQL catalog type int2vector is unavailable; cannot register loader",
        )
    info.register(conn)
    conn.adapters.register_loader("int2vector", Int2VectorLoader)  # type: ignore[attr-defined]


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
                        WHEN 'm' THEN 'materialized_view'
                        ELSE c.relkind::text
                      END AS object_type,
                      c.oid AS oid,
                      obj_description(c.oid, 'pg_class') AS comment
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
                    oid = int(row["oid"])
                    cols = self._columns(conn, oid)
                    ddl = None
                    if row["object_type"] in {"view", "materialized_view"}:
                        ddl = self._view_ddl(
                            conn,
                            row["schema_name"],
                            row["name"],
                            row["object_type"],
                        )
                    objects.append(
                        CollectedObject(
                            schema_name=row["schema_name"],
                            name=row["name"],
                            object_type=row["object_type"],
                            columns=cols,
                            ddl=ddl,
                            comment=row["comment"],
                            primary_key=self._primary_key(conn, oid),
                            foreign_keys=self._foreign_keys(conn, oid),
                            indexes=self._indexes(conn, oid),
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
              NOT a.attnotnull AS nullable,
              pg_catalog.pg_get_expr(ad.adbin, ad.adrelid) AS default_value,
              col_description(a.attrelid, a.attnum) AS comment
            FROM pg_catalog.pg_attribute a
            LEFT JOIN pg_catalog.pg_attrdef ad
              ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
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
                default_value=r["default_value"],
                comment=r["comment"],
            )
            for r in rows
        ]

    def _primary_key(self, conn: object, oid: int) -> list[str]:
        sql = text(
            """
            SELECT a.attname AS name
            FROM pg_catalog.pg_index i
            JOIN pg_catalog.pg_attribute a
              ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = :oid AND i.indisprimary
            ORDER BY array_position(i.indkey, a.attnum)
            """
        )
        rows = conn.execute(sql, {"oid": oid}).mappings().all()  # type: ignore[attr-defined]
        return [r["name"] for r in rows]

    def _foreign_keys(self, conn: object, oid: int) -> list[CollectedForeignKey]:
        sql = text(
            """
            SELECT
              con.conname AS name,
              con.conkey AS conkey,
              con.confkey AS confkey,
              nsp.nspname AS ref_schema,
              rel.relname AS ref_table,
              con.confrelid AS confrelid
            FROM pg_catalog.pg_constraint con
            JOIN pg_catalog.pg_class rel ON rel.oid = con.confrelid
            JOIN pg_catalog.pg_namespace nsp ON nsp.oid = rel.relnamespace
            WHERE con.conrelid = :oid AND con.contype = 'f'
            ORDER BY con.conname
            """
        )
        rows = conn.execute(sql, {"oid": oid}).mappings().all()  # type: ignore[attr-defined]
        out: list[CollectedForeignKey] = []
        for r in rows:
            cols = self._attnames(conn, oid, list(r["conkey"] or []))
            ref_cols = self._attnames(
                conn, int(r["confrelid"]), list(r["confkey"] or [])
            )
            out.append(
                CollectedForeignKey(
                    name=r["name"],
                    columns=cols,
                    ref_schema=r["ref_schema"],
                    ref_table=r["ref_table"],
                    ref_columns=ref_cols,
                )
            )
        return out

    def _attnames(self, conn: object, relid: int, attnums: list[int]) -> list[str]:
        if not attnums:
            return []
        sql = text(
            """
            SELECT a.attnum, a.attname
            FROM pg_catalog.pg_attribute a
            WHERE a.attrelid = :relid AND a.attnum = ANY(:attnums)
            """
        )
        rows = conn.execute(  # type: ignore[attr-defined]
            sql, {"relid": relid, "attnums": attnums}
        ).mappings().all()
        by_num = {int(r["attnum"]): r["attname"] for r in rows}
        return [by_num[n] for n in attnums if n in by_num]

    def _indexes(self, conn: object, oid: int) -> list[CollectedIndex]:
        sql = text(
            """
            SELECT
              i.relname AS name,
              ix.indisunique AS is_unique,
              ix.indkey AS indkey
            FROM pg_catalog.pg_index ix
            JOIN pg_catalog.pg_class i ON i.oid = ix.indexrelid
            WHERE ix.indrelid = :oid AND NOT ix.indisprimary
            ORDER BY i.relname
            """
        )
        rows = conn.execute(sql, {"oid": oid}).mappings().all()  # type: ignore[attr-defined]
        out: list[CollectedIndex] = []
        for r in rows:
            # indkey is an int2vector; exclude expression-only (0) slots.
            attnums = [int(n) for n in (r["indkey"] or []) if int(n) > 0]
            cols = self._attnames(conn, oid, attnums)
            out.append(
                CollectedIndex(
                    name=r["name"],
                    columns=cols,
                    is_unique=bool(r["is_unique"]),
                )
            )
        return out

    def _view_ddl(
        self, conn: object, schema: str, name: str, object_type: str
    ) -> str | None:
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
                keyword = (
                    "MATERIALIZED VIEW"
                    if object_type == "materialized_view"
                    else "VIEW"
                )
                return f"CREATE {keyword} {schema}.{name} AS\n{row['ddl']}"
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

        @event.listens_for(eng, "connect")
        def _register_pg_catalog_adapters(dbapi_conn, _connection_record):  # noqa: ANN001
            register_int2vector_loader(dbapi_conn)

        original_dispose = eng.dispose

        def dispose(*args, **kwargs):  # noqa: ANN002, ANN003
            try:
                return original_dispose(*args, **kwargs)
            finally:
                tls_cm.__exit__(None, None, None)

        eng.dispose = dispose  # type: ignore[method-assign]
        return eng
