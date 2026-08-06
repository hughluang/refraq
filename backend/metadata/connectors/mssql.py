"""MSSQL structure connector via sys.* catalog views."""

from __future__ import annotations

from urllib.parse import quote_plus

from sqlalchemy import create_engine, text

from backend.metadata.connectors.base import (
    CollectedColumn,
    CollectedObject,
    CollectedStructure,
    ConnectionEndpoint,
    ConnectorError,
)


class MssqlConnector:
    engine = "mssql"

    def test_connection(self, endpoint: ConnectionEndpoint) -> None:
        eng = self._engine(endpoint)
        try:
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError("JOB_CONNECTION_FAILED", str(exc)) from exc
        finally:
            eng.dispose()

    def collect_structure(self, endpoint: ConnectionEndpoint) -> CollectedStructure:
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
                      o.object_id AS object_id
                    FROM sys.objects o
                    JOIN sys.schemas s ON s.schema_id = o.schema_id
                    WHERE o.type IN ('U', 'V')
                      AND s.name NOT IN ('sys', 'INFORMATION_SCHEMA')
                      {schema_clause}
                    ORDER BY s.name, o.name
                    """
                )
                rows = conn.execute(obj_sql, params).mappings().all()
                objects: list[CollectedObject] = []
                for row in rows:
                    if row["object_type"] not in {"table", "view"}:
                        continue
                    cols = self._columns(conn, int(row["object_id"]))
                    objects.append(
                        CollectedObject(
                            schema_name=row["schema_name"],
                            name=row["name"],
                            object_type=row["object_type"],
                            columns=cols,
                            ddl=None,
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
              t.name AS data_type,
              c.is_nullable AS nullable
            FROM sys.columns c
            JOIN sys.types t ON t.user_type_id = c.user_type_id
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
            )
            for r in rows
        ]

    def _engine(self, endpoint: ConnectionEndpoint):
        # Prefer pymssql URL; requires pymssql installed.
        user = quote_plus(endpoint.username)
        password = quote_plus(endpoint.password)
        db = quote_plus(endpoint.database_name)
        url = (
            f"mssql+pymssql://{user}:{password}"
            f"@{endpoint.host}:{endpoint.port}/{db}"
        )
        return create_engine(url, pool_pre_ping=True)
