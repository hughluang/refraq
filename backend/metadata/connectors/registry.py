"""Engine connector registry."""

from __future__ import annotations

from backend.metadata.connectors.base import EngineConnector
from backend.metadata.connectors.mssql import MssqlConnector
from backend.metadata.connectors.oracle import OracleConnector
from backend.metadata.connectors.postgresql import PostgresqlConnector

_REGISTRY: dict[str, EngineConnector] = {
    "postgresql": PostgresqlConnector(),
    "mssql": MssqlConnector(),
    "oracle": OracleConnector(),
}


def get_connector(engine: str) -> EngineConnector | None:
    return _REGISTRY.get(engine)
