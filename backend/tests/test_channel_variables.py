"""Global Variable store: conditional writes, expiry, and the size cap."""

from __future__ import annotations

from datetime import timedelta

from backend.channel.variables import VALUE_MAX_BYTES, get_variable_store, value_size
from backend.core.time import utc_now


def test_set_if_absent_and_compare_and_set() -> None:
    store = get_variable_store()
    first = store.apply(operation="set_if_absent", name="lease", value={"owner": "a"})
    second = store.apply(operation="set_if_absent", name="lease", value={"owner": "b"})
    assert first.applied is True
    assert second.applied is False
    assert second.value == {"owner": "a"}
    missed = store.apply(
        operation="compare_and_set",
        name="lease",
        value={"owner": "c"},
        expected={"owner": "nope"},
    )
    assert missed.applied is False
    swapped = store.apply(
        operation="compare_and_set",
        name="lease",
        value={"owner": "c"},
        expected={"owner": "a"},
    )
    assert swapped.applied is True
    assert store.apply(operation="get", name="lease").value == {"owner": "c"}


def test_expired_value_is_absent() -> None:
    store = get_variable_store()
    past = utc_now() - timedelta(seconds=30)
    store.apply(operation="set", name="lease", value=1, ttl_sec=1, now=past)
    assert store.apply(operation="get", name="lease").found is False
    again = store.apply(operation="set_if_absent", name="lease", value=2)
    assert again.applied is True
    assert again.value == 2


def test_oversize_value_is_rejected_by_the_cap() -> None:
    blob = "x" * (VALUE_MAX_BYTES + 1)
    assert value_size(blob) > VALUE_MAX_BYTES
