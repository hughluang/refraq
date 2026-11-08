"""Fraction-less change-log upper bounds name the whole second."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.core.time import format_instant
from backend.entity.routers.entities import _occurred_to_bound

_HISTORY_SERVICE = (
    Path(__file__).resolve().parents[1] / "entity" / "history" / "service.py"
)


def test_fractionless_upper_bound_includes_the_rest_of_the_second() -> None:
    within = datetime(2026, 10, 28, 23, 40, 0, 739746, tzinfo=timezone.utc)
    published = format_instant(within)
    bound = _occurred_to_bound(published)
    assert published == "2026-10-28T23:40:00Z"
    assert bound == within.replace(microsecond=0) + timedelta(seconds=1) - timedelta(
        microseconds=1
    )
    assert within <= bound
    nxt = within.replace(microsecond=0) + timedelta(seconds=1)
    assert not nxt <= bound


def test_fractional_upper_bound_stays_exact() -> None:
    start = datetime(2026, 10, 28, 23, 40, tzinfo=timezone.utc)
    within = start.replace(microsecond=739746)
    exact = _occurred_to_bound("2026-10-28T23:40:00.000000Z")
    assert exact == start
    assert not within <= exact
    same = _occurred_to_bound("2026-10-28T23:40:00.739746Z")
    assert same == within


def test_missing_upper_bound_stays_open() -> None:
    assert _occurred_to_bound(None) is None
    assert _occurred_to_bound("") is None


def test_change_log_bounds_live_outside_the_http_router() -> None:
    assert not _occurred_to_bound.__module__.startswith("backend.entity.routers")
    tree = ast.parse(_HISTORY_SERVICE.read_text(encoding="utf-8"))
    imported = [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and isinstance(node.module, str)
    ]
    assert not any(name.startswith("backend.entity.routers") for name in imported)
