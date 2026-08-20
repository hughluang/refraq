"""Automatic join insert-vs-skip decisions."""

from __future__ import annotations

import pytest

from backend.metadata.catalog.join_origin import decide_automatic_insert


@pytest.mark.parametrize(
    ("existing_rejected", "expected"),
    [
        (None, "insert"),
        (False, "skip_protected"),
        (True, "skip_rejected"),
    ],
)
def test_decide_automatic_insert(
    existing_rejected: bool | None,
    expected: str,
) -> None:
    assert decide_automatic_insert(existing_rejected=existing_rejected) == expected
