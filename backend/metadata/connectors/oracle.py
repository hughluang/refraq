"""Oracle structure connector via ALL_*/DBA_* views."""

from __future__ import annotations

import os
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text

from backend.metadata.connectors.base import (
    CollectedColumn,
    CollectedObject,
    CollectedStructure,
    SourceEndpoint,
    ConnectorError,
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

    def collect_structure(self, endpoint: SourceEndpoint) -> CollectedStructure:
        eng = self._engine(endpoint)
        owner_filter = (endpoint.schema_filter or endpoint.username or "").upper()
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
                    ORDER BY 1, 2
                    """
                )
                rows = conn.execute(obj_sql, params).mappings().all()
                objects: list[CollectedObject] = []
                for row in rows:
                    cols = self._columns(conn, row["schema_name"], row["name"])
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

    def _columns(
        self, conn: object, owner: str, table_name: str
    ) -> list[CollectedColumn]:
        sql = text(
            """
            SELECT
              column_name AS name,
              column_id AS ordinal,
              data_type AS data_type,
              CASE nullable WHEN 'Y' THEN 1 ELSE 0 END AS nullable
            FROM all_tab_columns
            WHERE owner = :owner AND table_name = :table_name
            ORDER BY column_id
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
            )
            for r in rows
        ]

    def _engine(self, endpoint: SourceEndpoint):
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
                import oracledb

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
        return create_engine(url, pool_pre_ping=True)
