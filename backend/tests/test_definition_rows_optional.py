"""DDL collection is optional: null definition / query failure must not abort."""

from __future__ import annotations

from unittest.mock import patch

from backend.metadata.connectors.mssql import _definition_rows as mssql_definition_rows
from backend.metadata.connectors.oracle import _definition_rows as oracle_definition_rows
from backend.metadata.connectors.structure_rows import DefinitionRow


def test_mssql_definition_rows_null_ddl() -> None:
    with patch(
        "backend.metadata.connectors.mssql.stream_mappings",
        return_value=iter([{"object_key": 7, "ddl": None}]),
    ):
        rows = list(mssql_definition_rows(object(), {}))
    assert rows == [DefinitionRow(object_key="7", ddl=None)]


def test_mssql_definition_rows_query_failure() -> None:
    with patch(
        "backend.metadata.connectors.mssql.stream_mappings",
        side_effect=RuntimeError("encrypted module"),
    ):
        rows = list(mssql_definition_rows(object(), {}))
    assert rows == []


def test_oracle_definition_rows_null_ddl() -> None:
    with patch(
        "backend.metadata.connectors.oracle.stream_mappings",
        return_value=iter(
            [
                {
                    "schema_name": "HR",
                    "object_name": "FN_OPEN",
                    "object_type": "function",
                    "ddl": None,
                }
            ]
        ),
    ):
        rows = list(oracle_definition_rows(object(), {"owner": "HR"}))
    assert rows == [DefinitionRow(object_key="function:HR.FN_OPEN", ddl=None)]


def test_oracle_definition_rows_get_ddl_failure() -> None:
    with patch(
        "backend.metadata.connectors.oracle.stream_mappings",
        side_effect=RuntimeError("ORA-31603"),
    ):
        rows = list(oracle_definition_rows(object(), {"owner": "HR"}))
    assert rows == []
