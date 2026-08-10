"""Unit tests for PostgreSQL int2vector → list[int] loader (no live DB)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.metadata.connectors.base import ConnectorError
from backend.metadata.connectors.postgresql import (
    Int2VectorLoader,
    register_int2vector_loader,
)

# Stable catalog OID; Loader only needs it for construction in unit tests.
_INT2VECTOR_OID = 22


def _load(data: bytes | bytearray | memoryview) -> list[int]:
    return Int2VectorLoader(_INT2VECTOR_OID).load(data)


def test_int2vector_loader_multi_column() -> None:
    assert _load(b"1 2 3") == [1, 2, 3]


def test_int2vector_loader_single_column() -> None:
    assert _load(b"1") == [1]


def test_int2vector_loader_empty() -> None:
    assert _load(b"") == []
    assert _load(b"   ") == []


def test_int2vector_loader_memoryview() -> None:
    assert _load(memoryview(b"2 0 4")) == [2, 0, 4]


def test_register_int2vector_loader_fails_when_type_missing() -> None:
    with patch(
        "backend.metadata.connectors.postgresql.TypeInfo.fetch",
        return_value=None,
    ):
        with pytest.raises(ConnectorError, match="int2vector") as exc_info:
            register_int2vector_loader(MagicMock())
    assert exc_info.value.code == "JOB_ENDPOINT_FAILED"


def test_indkey_string_char_iteration_is_the_failure_mode() -> None:
    # Without a loader, psycopg returns space-separated text; iterating the
    # str yields spaces and matches JOB_COLLECT_FAILED in the wild.
    indkey = "1 2"
    with pytest.raises(ValueError, match="invalid literal for int"):
        _ = [int(n) for n in (indkey or []) if int(n) > 0]
