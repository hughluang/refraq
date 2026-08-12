"""Join Origin decision table (single deep-module interface)."""

from __future__ import annotations

import pytest

from backend.metadata.catalog.join_origin import resolve_join_write


@pytest.mark.parametrize(
    ("existing_origin", "incoming_origin", "expected"),
    [
        ("human", "foreign_key", "keep_existing"),
        ("mcp", "foreign_key", "keep_existing"),
        (None, "foreign_key", "apply"),
        ("foreign_key", "foreign_key", "apply"),
        ("human", "human", "apply"),
        ("mcp", "human", "apply"),
        ("foreign_key", "human", "apply"),
        ("human", "mcp", "apply"),
    ],
)
def test_resolve_join_write_decision_table(
    existing_origin: str | None,
    incoming_origin: str,
    expected: str,
) -> None:
    assert (
        resolve_join_write(
            existing_origin=existing_origin,
            incoming_origin=incoming_origin,
        )
        == expected
    )
