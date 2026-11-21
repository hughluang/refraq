"""MySQL Metadata adapter; database is the sole catalog/schema scope."""

from __future__ import annotations

from pymysql.constants import FIELD_TYPE
from sqlalchemy import URL, create_engine, inspect, text
from sqlalchemy.pool import NullPool
from sqlglot import exp, parse_one

from backend.metadata.query.guards import assert_readonly_single_statement

from backend.metadata.connectors.base import (
    CollectedColumn,
    CollectedForeignKey,
    CollectedIndex,
    CollectedObject,
    CollectedStructure,
    ConnectorError,
    QueryColumn,
    fetch_query_result,
)


class MysqlConnector:
    engine = "mysql"

    def _engine(self, endpoint, *, timeout_sec=10):
        if (
            endpoint.ssl_mode != "disable"
            or any(
                (
                    endpoint.ssl_root_cert,
                    endpoint.ssl_client_cert,
                    endpoint.ssl_client_key,
                )
            )
            or endpoint.extra
        ):
            raise ConnectorError(
                "JOB_ENDPOINT_FAILED", "Unsupported MySQL access options"
            )
        return create_engine(
            URL.create(
                "mysql+pymysql",
                username=endpoint.username,
                password=endpoint.password,
                host=endpoint.host,
                port=endpoint.port,
                database=endpoint.database_name,
            ),
            connect_args={
                "charset": "utf8mb4",
                "connect_timeout": timeout_sec,
                "read_timeout": timeout_sec,
                "write_timeout": timeout_sec,
                "ssl_disabled": True,
                "local_infile": False,
            },
            poolclass=NullPool,
            hide_parameters=True,
        )

    def _prove_scope(self, conn, endpoint):
        found = conn.execute(
            text(
                "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
                "WHERE BINARY SCHEMA_NAME = BINARY :database"
            ),
            {"database": endpoint.database_name},
        ).scalar()
        if found is None:
            raise ConnectorError(
                "JOB_ENDPOINT_FAILED", "MySQL database scope is unavailable"
            )

    def test_connection(self, endpoint):
        eng = self._engine(endpoint)
        try:
            with eng.connect() as conn:
                self._prove_scope(conn, endpoint)
        except ConnectorError:
            raise
        except Exception:
            raise ConnectorError(
                "JOB_ENDPOINT_FAILED", "MySQL endpoint unavailable"
            ) from None
        finally:
            eng.dispose()

    def collect_structure(self, endpoint, progress=None):
        eng = self._engine(endpoint)
        try:
            with eng.connect() as conn:
                self._prove_scope(conn, endpoint)
                schema = endpoint.database_name
                inspector = inspect(conn)
                if progress is not None:
                    progress.listing_objects(schema)
                tables = inspector.get_table_names(schema=schema)
                views = inspector.get_view_names(schema=schema)
                if progress is not None:
                    progress.listed_objects(len(tables) + len(views))
                columns = conn.execute(
                    text(
                        "SELECT TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION, COLUMN_TYPE, "
                        "IS_NULLABLE, COLUMN_DEFAULT, COLUMN_COMMENT "
                        "FROM information_schema.COLUMNS "
                        "WHERE BINARY TABLE_SCHEMA = BINARY :database ORDER BY TABLE_NAME, ORDINAL_POSITION"
                    ),
                    {"database": schema},
                ).mappings()
                by_table = {}
                for col in columns:
                    by_table.setdefault(col["TABLE_NAME"], []).append(
                        CollectedColumn(
                            name=col["COLUMN_NAME"],
                            ordinal=col["ORDINAL_POSITION"],
                            data_type=col["COLUMN_TYPE"],
                            nullable=col["IS_NULLABLE"] == "YES",
                            default_value=col["COLUMN_DEFAULT"],
                            comment=col["COLUMN_COMMENT"] or None,
                        )
                    )
                index_parts = conn.execute(
                    text(
                        "SELECT TABLE_NAME, INDEX_NAME, COLUMN_NAME, NON_UNIQUE "
                        "FROM information_schema.STATISTICS "
                        "WHERE BINARY TABLE_SCHEMA = BINARY :database "
                        "ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX"
                    ),
                    {"database": schema},
                ).mappings()
                indexes = {}
                for part in index_parts:
                    name = part["INDEX_NAME"]
                    column = part["COLUMN_NAME"]
                    if column is None:
                        raise ConnectorError("JOB_COLLECT_FAILED", "MySQL expression indexes are unsupported")
                    if name == "PRIMARY":
                        continue
                    table_indexes = indexes.setdefault(part["TABLE_NAME"], {})
                    if name not in table_indexes:
                        table_indexes[name] = CollectedIndex(
                            name=name, columns=[], is_unique=not part["NON_UNIQUE"],
                        )
                    table_indexes[name].columns.append(column)
                objects = []
                quote = conn.dialect.identifier_preparer.quote_identifier
                for name, kind in [(n, "table") for n in tables] + [
                    (n, "view") for n in views
                ]:
                    obj = CollectedObject(
                        schema_name=schema,
                        name=name,
                        object_type=kind,
                        columns=by_table.get(name, []),
                    )
                    if kind == "table":
                        obj.comment = inspector.get_table_comment(
                            name, schema=schema
                        ).get("text")
                        obj.primary_key = inspector.get_pk_constraint(
                            name, schema=schema
                        )["constrained_columns"]
                        obj.foreign_keys = [
                            CollectedForeignKey(
                                name=fk["name"],
                                columns=fk["constrained_columns"],
                                ref_schema=fk["referred_schema"] or schema,
                                ref_table=fk["referred_table"],
                                ref_columns=fk["referred_columns"],
                            )
                            for fk in inspector.get_foreign_keys(name, schema=schema)
                        ]
                        obj.indexes = list(indexes.get(name, {}).values())
                    ddl = conn.exec_driver_sql(
                        f"SHOW CREATE {kind.upper()} {quote(schema)}.{quote(name)}"
                    ).first()
                    if ddl is not None:
                        obj.ddl = ddl[1]
                    objects.append(obj)
                if progress is not None:
                    progress.assembled(len(objects))
                return CollectedStructure(objects=objects)
        except ConnectorError:
            raise
        except Exception:
            raise ConnectorError(
                "JOB_COLLECT_FAILED", "MySQL structure collection failed"
            ) from None
        finally:
            eng.dispose()

    def run_readonly(self, endpoint, sql, *, max_rows, timeout_sec):
        sql = assert_readonly_single_statement(sql, engine="mysql")
        limited = parse_one(sql, read="mysql")
        limit = limited.args.get("limit")
        cap = max_rows + 1
        if limit is not None:
            value = limit.expression
            if not isinstance(value, exp.Literal) or not value.is_int:
                raise ConnectorError("QUERY_ENDPOINT_FAILED", "MySQL LIMIT must be an integer")
            cap = min(cap, int(value.this))
        limited = limited.limit(cap)
        eng = self._engine(endpoint, timeout_sec=timeout_sec)
        try:
            with eng.connect() as conn:
                conn.exec_driver_sql(
                    f"SET SESSION MAX_EXECUTION_TIME = {int(timeout_sec) * 1000}"
                )
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                conn.exec_driver_sql("START TRANSACTION READ ONLY")
                result = conn.execution_options(
                    stream_results=True, no_parameters=True,
                ).exec_driver_sql(limited.sql(dialect="mysql", comments=False))
                temporal_types = {
                    FIELD_TYPE.DATE: "date",
                    FIELD_TYPE.DATETIME: "datetime",
                    FIELD_TYPE.TIMESTAMP: "timestamp",
                    FIELD_TYPE.TIME: "interval",
                }
                column_info = [
                    QueryColumn(
                        name=column[0],
                        native_type=(
                            f"{temporal_types[column[1]]}({column[5]})"
                            if column[1] in temporal_types and column[5] is not None
                            else temporal_types.get(column[1])
                        ),
                        nullable=column[6] if isinstance(column[6], bool) else None,
                    )
                    for column in result.cursor.description
                ]
                return fetch_query_result(
                    result, max_rows=max_rows, column_info=column_info
                )
        except Exception as exc:
            original = getattr(exc, "orig", exc)
            number = original.args[0] if original.args else None
            code = (
                "QUERY_TIMEOUT" if number in {2013, 3024} else "QUERY_ENDPOINT_FAILED"
            )
            raise ConnectorError(
                code,
                "MySQL query timed out"
                if code == "QUERY_TIMEOUT"
                else "MySQL query failed",
            ) from None
        finally:
            eng.dispose()

    def run_statement(self, endpoint, sql, *, max_rows, timeout_sec, params=None):
        raise ConnectorError(
            "QUERY_ENDPOINT_FAILED", "MySQL author statements are unsupported"
        )

    def stream_statement(self, endpoint, sql, *, chunk_rows, deadline):
        raise ConnectorError(
            "QUERY_ENDPOINT_FAILED", "MySQL author statement streams are unsupported"
        )
