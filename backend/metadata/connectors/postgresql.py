"""PostgreSQL structure connector via pg_catalog."""

from __future__ import annotations

from urllib.parse import quote_plus

from psycopg.adapt import Loader
from psycopg.types import TypeInfo
from sqlalchemy import create_engine, event, text

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
from backend.metadata.connectors.tls import postgres_connect_args, tls_temp_files


# Connector contract: pool connections load int2vector as list[int].
# psycopg3 has no built-in loader; collect no longer reads indkey in Python,
# but other catalog adapters may still see the wire form.

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
                        object_key=str(int(row["oid"])),
                        schema_name=row["schema_name"],
                        name=row["name"],
                        object_type=row["object_type"],
                        comment=row["comment"],
                    )
                    for row in stream_mappings(conn, _OBJECT_SQL, params)
                ]
                objects.extend(
                    ObjectRow(
                        object_key=str(int(row["oid"])),
                        schema_name=row["schema_name"],
                        name=row["name"],
                        object_type=row["object_type"],
                        comment=row["comment"],
                    )
                    for row in stream_mappings(conn, _ROUTINE_OBJECT_SQL, params)
                )
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

    def _engine(self, endpoint: SourceEndpoint):
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


_SCHEMA_SCOPE = """
  AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
  AND n.nspname NOT LIKE 'pg_toast%%'
  AND n.nspname NOT LIKE 'pg_temp%%'
  AND n.nspname = :schema_filter
"""

_OBJECT_SQL = text(
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
      {_SCHEMA_SCOPE}
    ORDER BY n.nspname, c.relname
    """
)

_COLUMN_SQL = text(
    f"""
    SELECT
      a.attrelid AS object_key,
      a.attname AS name,
      a.attnum AS ordinal,
      pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
      NOT a.attnotnull AS nullable,
      pg_catalog.pg_get_expr(ad.adbin, ad.adrelid) AS default_value,
      col_description(a.attrelid, a.attnum) AS comment
    FROM pg_catalog.pg_attribute a
    JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_catalog.pg_attrdef ad
      ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
    WHERE a.attnum > 0
      AND NOT a.attisdropped
      AND c.relkind IN ('r', 'p', 'v', 'm')
      {_SCHEMA_SCOPE}
    ORDER BY a.attrelid, a.attnum
    """
)

_PRIMARY_KEY_SQL = text(
    f"""
    SELECT
      i.indrelid AS object_key,
      a.attname AS name,
      array_position(i.indkey, a.attnum) AS ordinal
    FROM pg_catalog.pg_index i
    JOIN pg_catalog.pg_class c ON c.oid = i.indrelid
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_catalog.pg_attribute a
      ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
    WHERE i.indisprimary
      AND c.relkind IN ('r', 'p', 'v', 'm')
      {_SCHEMA_SCOPE}
    ORDER BY i.indrelid, array_position(i.indkey, a.attnum)
    """
)

_FOREIGN_KEY_SQL = text(
    f"""
    SELECT
      con.conrelid AS object_key,
      con.conname AS constraint_name,
      local_att.attname AS column_name,
      nsp.nspname AS ref_schema,
      rel.relname AS ref_table,
      ref_att.attname AS ref_column,
      ord.ordinality AS ordinal
    FROM pg_catalog.pg_constraint con
    JOIN pg_catalog.pg_class src ON src.oid = con.conrelid
    JOIN pg_catalog.pg_namespace n ON n.oid = src.relnamespace
    JOIN pg_catalog.pg_class rel ON rel.oid = con.confrelid
    JOIN pg_catalog.pg_namespace nsp ON nsp.oid = rel.relnamespace
    JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS ord(attnum, ordinality)
      ON true
    JOIN pg_catalog.pg_attribute local_att
      ON local_att.attrelid = con.conrelid AND local_att.attnum = ord.attnum
    JOIN LATERAL unnest(con.confkey) WITH ORDINALITY AS ref_ord(attnum, ordinality)
      ON ref_ord.ordinality = ord.ordinality
    JOIN pg_catalog.pg_attribute ref_att
      ON ref_att.attrelid = con.confrelid AND ref_att.attnum = ref_ord.attnum
    WHERE con.contype = 'f'
      AND src.relkind IN ('r', 'p', 'v', 'm')
      {_SCHEMA_SCOPE}
    ORDER BY con.conrelid, con.conname, ord.ordinality
    """
)

_INDEX_SQL = text(
    f"""
    SELECT
      ix.indrelid AS object_key,
      i.relname AS index_name,
      a.attname AS column_name,
      ord.ordinality AS ordinal,
      ix.indisunique AS is_unique
    FROM pg_catalog.pg_index ix
    JOIN pg_catalog.pg_class i ON i.oid = ix.indexrelid
    JOIN pg_catalog.pg_class c ON c.oid = ix.indrelid
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    JOIN LATERAL unnest(ix.indkey) WITH ORDINALITY AS ord(attnum, ordinality)
      ON true
    JOIN pg_catalog.pg_attribute a
      ON a.attrelid = ix.indrelid AND a.attnum = ord.attnum
    WHERE NOT ix.indisprimary
      AND ord.attnum > 0
      AND c.relkind IN ('r', 'p', 'v', 'm')
      {_SCHEMA_SCOPE}
    ORDER BY ix.indrelid, i.relname, ord.ordinality
    """
)

_DEFINITION_SQL = text(
    f"""
    SELECT
      c.oid AS object_key,
      n.nspname AS schema_name,
      c.relname AS name,
      CASE c.relkind
        WHEN 'm' THEN 'materialized_view'
        ELSE 'view'
      END AS object_type,
      pg_catalog.pg_get_viewdef(c.oid, true) AS ddl
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind IN ('v', 'm')
      {_SCHEMA_SCOPE}
    """
)

_ROUTINE_OBJECT_SQL = text(
    f"""
    SELECT
      n.nspname AS schema_name,
      CASE
        WHEN pg_catalog.pg_get_function_identity_arguments(p.oid) = ''
          THEN p.proname
        ELSE p.proname || '(' || pg_catalog.pg_get_function_identity_arguments(p.oid) || ')'
      END AS name,
      CASE p.prokind
        WHEN 'p' THEN 'procedure'
        ELSE 'function'
      END AS object_type,
      p.oid AS oid,
      obj_description(p.oid, 'pg_proc') AS comment
    FROM pg_catalog.pg_proc p
    JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
    WHERE p.prokind IN ('f', 'p')
      {_SCHEMA_SCOPE}
    ORDER BY n.nspname, p.proname, p.oid
    """
)

_ROUTINE_DEFINITION_SQL = text(
    f"""
    SELECT
      p.oid AS object_key,
      pg_catalog.pg_get_functiondef(p.oid) AS ddl
    FROM pg_catalog.pg_proc p
    JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
    WHERE p.prokind IN ('f', 'p')
      {_SCHEMA_SCOPE}
    """
)


def _column_rows(conn: object, params: dict[str, object]):
    for row in stream_mappings(conn, _COLUMN_SQL, params):
        yield ColumnRow(
            object_key=str(int(row["object_key"])),
            name=row["name"],
            ordinal=int(row["ordinal"]),
            data_type=row["data_type"],
            nullable=bool(row["nullable"]),
            default_value=row["default_value"],
            comment=row["comment"],
        )


def _primary_key_rows(conn: object, params: dict[str, object]):
    for row in stream_mappings(conn, _PRIMARY_KEY_SQL, params):
        yield KeyColumnRow(
            object_key=str(int(row["object_key"])),
            name=row["name"],
            ordinal=int(row["ordinal"] or 0),
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
            if not row["ddl"]:
                yield DefinitionRow(object_key=str(int(row["object_key"])), ddl=None)
                continue
            keyword = (
                "MATERIALIZED VIEW"
                if row["object_type"] == "materialized_view"
                else "VIEW"
            )
            ddl = f"CREATE {keyword} {row['schema_name']}.{row['name']} AS\n{row['ddl']}"
            yield DefinitionRow(object_key=str(int(row["object_key"])), ddl=ddl)
    except Exception:  # noqa: BLE001 — ddl optional
        pass
    try:
        for row in stream_mappings(conn, _ROUTINE_DEFINITION_SQL, params):
            ddl = str(row["ddl"]) if row["ddl"] else None
            yield DefinitionRow(object_key=str(int(row["object_key"])), ddl=ddl)
    except Exception:  # noqa: BLE001 — ddl optional
        return
