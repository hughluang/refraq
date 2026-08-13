"""Contract tests for backend.core.time."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel, ValidationError

from backend.core.time import (
    FixedClock,
    Instant,
    NaiveDateTimeError,
    UtcDateTime,
    ensure_aware_utc,
    format_instant,
    get_clock,
    parse_instant,
    reset_clock,
    resolve_wall_time,
    set_clock,
    utc_now,
)


def test_utc_now_is_aware_utc() -> None:
    reset_clock()
    now = utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_fixed_clock_freezes_and_resets() -> None:
    fixed = FixedClock(datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc))
    set_clock(fixed)
    assert utc_now() == datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    fixed.advance(timedelta(minutes=5))
    assert utc_now() == datetime(2026, 8, 12, 10, 5, tzinfo=timezone.utc)
    reset_clock()
    assert get_clock() is not fixed


def test_ensure_aware_utc_rejects_naive() -> None:
    with pytest.raises(NaiveDateTimeError):
        ensure_aware_utc(datetime(2026, 1, 1, 12, 0, 0))  # noqa: DTZ001


def test_ensure_aware_utc_normalizes_offset() -> None:
    value = datetime(2026, 1, 1, 20, 0, tzinfo=timezone(timedelta(hours=8)))
    assert ensure_aware_utc(value) == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def test_format_and_parse_instant_roundtrip() -> None:
    instant = datetime(2026, 8, 12, 2, 0, 0, tzinfo=timezone.utc)
    text = format_instant(instant)
    assert text.endswith("Z")
    assert parse_instant(text) == instant
    assert parse_instant("2026-08-12T10:00:00+08:00") == instant


def test_parse_instant_rejects_naive_string() -> None:
    with pytest.raises(ValueError):
        parse_instant("2026-08-12T10:00:00")


class _InstantModel(BaseModel):
    at: Instant


def test_instant_field_accepts_offset_and_emits_z() -> None:
    model = _InstantModel.model_validate({"at": "2026-08-12T10:00:00+08:00"})
    assert model.at == datetime(2026, 8, 12, 2, 0, tzinfo=timezone.utc)
    dumped = model.model_dump_json()
    assert '"2026-08-12T02:00:00Z"' in dumped


def test_instant_field_rejects_naive() -> None:
    with pytest.raises(ValidationError):
        _InstantModel.model_validate({"at": "2026-08-12T10:00:00"})


def test_utc_datetime_bind_rejects_naive() -> None:
    col = UtcDateTime()
    with pytest.raises(NaiveDateTimeError):
        col.process_bind_param(datetime(2026, 1, 1, 0, 0, 0), dialect=None)  # noqa: DTZ001


def test_utc_datetime_result_normalizes_naive_as_utc() -> None:
    col = UtcDateTime()
    value = col.process_result_value(
        datetime(2026, 1, 1, 0, 0, 0), dialect=None  # noqa: DTZ001
    )
    assert value == datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


def test_resolve_wall_time_ambiguous_uses_fold_one() -> None:
    # US Pacific 2025-11-02 01:30 exists twice; second occurrence is fold=1.
    tz = ZoneInfo("America/Los_Angeles")
    resolved = resolve_wall_time(2025, 11, 2, 1, 30, 0, tz)
    assert resolved == datetime(2025, 11, 2, 1, 30, tzinfo=tz, fold=1).astimezone(
        timezone.utc
    )


def test_resolve_wall_time_gap_advances_to_next_legal() -> None:
    # US Pacific 2025-03-09 02:30 does not exist; next legal is 03:00.
    tz = ZoneInfo("America/Los_Angeles")
    resolved = resolve_wall_time(2025, 3, 9, 2, 30, 0, tz)
    local = resolved.astimezone(tz)
    assert (local.hour, local.minute) == (3, 0)
