"""PostgreSQL routine identity signatures at the connector (no live DB)."""

from __future__ import annotations

from unittest.mock import patch

from backend.metadata.connectors.base import SourceEndpoint
from backend.metadata.connectors.postgresql import (
    PostgresqlConnector,
    _ROUTINE_DEFINITION_SQL,
    _ROUTINE_OBJECT_SQL,
)


def _endpoint() -> SourceEndpoint:
    return SourceEndpoint(
        engine="postgresql",
        host="127.0.0.1",
        port=5432,
        username="u",
        password="p",
        database_name="MES",
        schema_filter="public",
    )


class _FakeEngine:
    def connect(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def dispose(self) -> None:
        return None


def test_collect_structure_keeps_overload_identity_signatures() -> None:
    assert "pg_get_function_identity_arguments" in str(_ROUTINE_OBJECT_SQL)
    assert "pg_get_functiondef" in str(_ROUTINE_DEFINITION_SQL)

    def _stream(_conn: object, sql: object, _params: dict[str, object], **_kw: object):
        if sql is _ROUTINE_OBJECT_SQL:
            return iter(
                [
                    {
                        "oid": 11,
                        "schema_name": "public",
                        "name": "fn_open(integer)",
                        "object_type": "function",
                        "comment": None,
                    },
                    {
                        "oid": 12,
                        "schema_name": "public",
                        "name": "fn_open(text)",
                        "object_type": "function",
                        "comment": None,
                    },
                ]
            )
        return iter(())

    engine = _FakeEngine()
    connector = PostgresqlConnector()
    with (
        patch.object(PostgresqlConnector, "_engine", return_value=engine),
        patch(
            "backend.metadata.connectors.postgresql.stream_mappings",
            side_effect=_stream,
        ),
    ):
        collected = connector.collect_structure(_endpoint())

    names = sorted(obj.name for obj in collected.objects)
    assert names == ["fn_open(integer)", "fn_open(text)"]
    assert all(obj.object_type == "function" for obj in collected.objects)
