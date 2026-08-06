"""EngineConnector protocol and collected structure DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ConnectionEndpoint:
    engine: str
    host: str
    port: int
    username: str
    password: str
    database_name: str
    schema_filter: str | None = None


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

    def test_connection(self, endpoint: ConnectionEndpoint) -> None:
        """Raise on failure; return None on success."""

    def collect_structure(self, endpoint: ConnectionEndpoint) -> CollectedStructure:
        """Return complete structure for the Source scope, or raise."""


class ConnectorError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
