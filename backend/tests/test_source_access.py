"""Source access interprets Connector Spec (validate / project / endpoint)."""

from __future__ import annotations

from typing import Any

import pytest

from backend.metadata.connectors.specs import get_connector_spec
from backend.metadata.errors import SourceAccessInvalid
from backend.metadata.sources.access import (
    endpoint_from_access,
    project_access,
)


def _base_access(**scope: object) -> dict[str, Any]:
    access: dict[str, Any] = {
        "host": "db.example.internal",
        "port": 5432,
        "username": "meta",
        "password": "secret",
        "ssl_mode": "disable",
        "extra": {},
    }
    access.update(scope)
    return access


def test_postgres_endpoint_uses_database_and_schema() -> None:
    endpoint = endpoint_from_access(
        engine="postgresql",
        access=_base_access(database="mes", schema="public"),
    )
    assert endpoint.database_name == "mes"
    assert endpoint.schema_filter == "public"
    assert endpoint.host == "db.example.internal"
    assert endpoint.password == "secret"


def test_oracle_endpoint_uses_service_name_and_owner() -> None:
    endpoint = endpoint_from_access(
        engine="oracle",
        access=_base_access(
            port=1521,
            service_name="ORCL",
            owner="MES",
        ),
    )
    assert endpoint.database_name == "ORCL"
    assert endpoint.schema_filter == "MES"


def test_mssql_endpoint_uses_database_and_schema() -> None:
    endpoint = endpoint_from_access(
        engine="mssql",
        access=_base_access(port=1433, database="app", schema="dbo"),
    )
    assert endpoint.database_name == "app"
    assert endpoint.schema_filter == "dbo"


def test_scope_mapping_comes_from_spec_x_scope() -> None:
    pg = get_connector_spec("postgresql")["properties"]
    assert pg["database"]["x-scope"] == "catalog"
    assert pg["schema"]["x-scope"] == "schema"
    oracle = get_connector_spec("oracle")["properties"]
    assert oracle["service_name"]["x-scope"] == "catalog"
    assert oracle["owner"]["x-scope"] == "schema"


def test_endpoint_follows_synthetic_x_scope_not_engine_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = {
        "properties": {
            "host": {},
            "port": {},
            "username": {},
            "password": {},
            "lib": {"x-scope": "catalog"},
            "ns": {"x-scope": "schema"},
        }
    }
    monkeypatch.setattr(
        "backend.metadata.sources.access.connector_specs.get_connector_spec",
        lambda engine: spec,
    )
    endpoint = endpoint_from_access(
        engine="postgresql",
        access=_base_access(
            lib="CAT",
            ns="NS",
            database="would-be-wrong",
            schema="would-be-wrong",
        ),
    )
    assert endpoint.database_name == "CAT"
    assert endpoint.schema_filter == "NS"


def test_missing_x_scope_on_spec_is_authoring_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.metadata.sources.access.connector_specs.get_connector_spec",
        lambda engine: {"properties": {"database": {}}},
    )
    with pytest.raises(RuntimeError, match="must mark x-scope"):
        endpoint_from_access(engine="postgresql", access=_base_access())


def test_missing_scope_value_is_access_invalid() -> None:
    with pytest.raises(SourceAccessInvalid, match="access.database is required"):
        endpoint_from_access(
            engine="postgresql",
            access=_base_access(schema="public"),
        )


def test_project_access_strips_x_secret() -> None:
    projected = project_access(
        "postgresql",
        _base_access(
            database="mes",
            schema="public",
            ssl_root_cert="PEM",
        ),
    )
    assert "password" not in projected
    assert "ssl_root_cert" not in projected
    assert projected["host"] == "db.example.internal"
    assert projected["database"] == "mes"
    assert projected["schema"] == "public"
