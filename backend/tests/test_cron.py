"""Cron field parsing and day-skip next-fire search."""

from __future__ import annotations

import pytest

from backend.core.time import parse_instant
from backend.worker.cron import (
    ZoneCronSchedule,
    first_cron_fire_after,
    parse_cron_fields,
)


def _utc(expr: str) -> ZoneCronSchedule:
    return ZoneCronSchedule(expr, schedule_timezone="UTC")


def test_monthly_15th_advances_to_the_next_month() -> None:
    nxt = _utc("0 0 15 * *")._next_fire_after(parse_instant("2026-01-15T00:00:00Z"))
    assert nxt == parse_instant("2026-02-15T00:00:00Z")


def test_day_31_skips_months_that_do_not_have_it() -> None:
    schedule = _utc("0 0 31 * *")
    january = schedule._next_fire_after(parse_instant("2026-01-30T12:00:00Z"))
    assert january == parse_instant("2026-01-31T00:00:00Z")
    march = schedule._next_fire_after(january)
    assert march == parse_instant("2026-03-31T00:00:00Z")
    may = schedule._next_fire_after(march)
    assert may == parse_instant("2026-05-31T00:00:00Z")


def test_day_29_skips_a_non_leap_february() -> None:
    nxt = _utc("0 0 29 * *")._next_fire_after(parse_instant("2025-02-01T00:00:00Z"))
    assert nxt == parse_instant("2025-03-29T00:00:00Z")


def test_feb_29_waits_for_the_next_leap_day() -> None:
    nxt = _utc("0 0 29 2 *")._next_fire_after(parse_instant("2025-03-01T00:00:00Z"))
    assert nxt == parse_instant("2028-02-29T00:00:00Z")


def test_feb_29_crosses_the_non_leap_century() -> None:
    nxt = _utc("0 0 29 2 *")._next_fire_after(parse_instant("2096-03-01T00:00:00Z"))
    assert nxt == parse_instant("2104-02-29T00:00:00Z")


def test_feb_30_has_no_fire_within_eight_years() -> None:
    from zoneinfo import ZoneInfo

    fields = parse_cron_fields("0 0 30 2 *")
    assert (
        first_cron_fire_after(fields, ZoneInfo("UTC"), parse_instant("2026-01-01T00:00:00Z"))
        is None
    )


@pytest.mark.parametrize(
    "expr",
    [
        "60 * * * *",
        "0 24 * * *",
        "0 0 32 * *",
        "0 0 * 13 *",
        "0 0 * * 8",
        "*/0 * * * *",
        "0 0 * * 5-3",
        "-1 * * * *",
        "nope * * * *",
        "0 2 1 * 1",
        "0 2 */2 * 1",
    ],
)
def test_parse_rejects_out_of_range_step_order_and_both_day_fields(expr: str) -> None:
    with pytest.raises(ValueError):
        parse_cron_fields(expr)


def test_sunday_seven_is_sunday_zero() -> None:
    fields = parse_cron_fields("0 0 * * 7")
    assert fields[4] == {0}
