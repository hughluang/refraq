"""EngineConnector protocol and collected structure DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SourceEndpoint:
    engine: str
    host: str
    port: int
    username: str
    password: str
    database_name: str
    schema_filter: str | None = None
    ssl_mode: str = "require"
    ssl_root_cert: str | None = None
    ssl_client_cert: str | None = None
    ssl_client_key: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


def endpoint_from_access(
    *,
    engine: str,
    access: dict[str, Any],
    database_name: str,
    schema_filter: str | None = None,
) -> SourceEndpoint:
    extra_raw = access.get("extra") or {}
    extra = {
        str(k): str(v)
        for k, v in extra_raw.items()
        if isinstance(k, str) and v is not None
    }
    root = access.get("ssl_root_cert")
    client_cert = access.get("ssl_client_cert")
    client_key = access.get("ssl_client_key")
    return SourceEndpoint(
        engine=engine,
        host=str(access["host"]),
        port=int(access["port"]),
        username=str(access["username"]),
        password=str(access["password"]),
        database_name=database_name,
        schema_filter=schema_filter,
        ssl_mode=str(access.get("ssl_mode") or "require"),
        ssl_root_cert=str(root) if root else None,
        ssl_client_cert=str(client_cert) if client_cert else None,
        ssl_client_key=str(client_key) if client_key else None,
        extra=extra,
    )


@dataclass
class CollectedColumn:
    name: str
    ordinal: int
    data_type: str
    nullable: bool


@dataclass
class CollectedObject:
    schema_name: str
    name: str
    object_type: str  # table | view
    columns: list[CollectedColumn] = field(default_factory=list)
    ddl: str | None = None


@dataclass
class CollectedStructure:
    objects: list[CollectedObject] = field(default_factory=list)


class EngineConnector(Protocol):
    engine: str

    def test_connection(self, endpoint: SourceEndpoint) -> None:
        """Raise on failure; return None on success."""

    def collect_structure(self, endpoint: SourceEndpoint) -> CollectedStructure:
        """Return complete structure for the Source scope, or raise."""


class ConnectorError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
