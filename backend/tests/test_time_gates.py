"""Static gates for the unified time contract."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent


def _iter_py_files() -> list[Path]:
    files: list[Path] = []
    for path in BACKEND.rglob("*.py"):
        if "alembic" in path.parts or "__pycache__" in path.parts:
            continue
        files.append(path)
    return files


def test_no_utcnow_or_utcfromtimestamp() -> None:
    banned = ("utcnow", "utcfromtimestamp")
    offenders: list[str] = []
    for path in _iter_py_files():
        if path.name == "test_time_gates.py":
            continue
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in banned:
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not offenders, "forbidden datetime.utcnow/utcfromtimestamp:\n" + "\n".join(
        offenders
    )


def test_no_naive_isoformat_z_concat() -> None:
    pattern = re.compile(r"""\.isoformat\(\)\s*\+\s*['\"]Z['\"]""")
    offenders: list[str] = []
    for path in _iter_py_files():
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{i}: {line.strip()}")
    assert not offenders, "forbidden naive.isoformat()+Z:\n" + "\n".join(offenders)


def test_celery_enable_utc() -> None:
    from backend.worker.app import celery_app

    assert celery_app.conf.enable_utc is True
    assert str(celery_app.conf.timezone) in {"UTC", "utc"}


@pytest.mark.parametrize(
    "cron,tz_name,after,expected_local_hm,expected_fold",
    [
        # Daily 02:30 America/Los_Angeles on spring-forward day → 03:00
        (
            "30 2 * * *",
            "America/Los_Angeles",
            "2025-03-09T08:00:00Z",  # before local 02:30 gap
            (3, 0),
            0,
        ),
        # Daily 02:00 on fall-back day → unambiguous 02:00 PST (not in the repeated hour)
        (
            "0 2 * * *",
            "America/Los_Angeles",
            "2025-11-02T09:30:00Z",  # local 01:30 fold=1
            (2, 0),
            0,
        ),
        # Hourly :45 after spring 01:45 → gap 02:45 resolved to next legal 03:00
        # (locks daily-for-all; not Dagster hourly which would fire 03:45)
        (
            "45 * * * *",
            "America/Los_Angeles",
            "2025-03-09T09:45:00Z",  # local 01:45 PST
            (3, 0),
            0,
        ),
        # Hourly :45 after fall 00:45 → 01:45 fold=1 once (not both folds)
        (
            "45 * * * *",
            "America/Los_Angeles",
            "2025-11-02T07:45:00Z",  # local 00:45 PDT
            (1, 45),
            1,
        ),
    ],
)
def test_zone_cron_dst_wall_clock(
    cron, tz_name, after, expected_local_hm, expected_fold
) -> None:
    from zoneinfo import ZoneInfo

    from backend.core.time import parse_instant
    from backend.worker.cron import ZoneCronSchedule

    schedule = ZoneCronSchedule(cron, schedule_timezone=tz_name)
    nxt = schedule._next_fire_after(parse_instant(after))
    local = nxt.astimezone(ZoneInfo(tz_name))
    assert (local.hour, local.minute) == expected_local_hm
    assert local.fold == expected_fold


def test_zone_cron_hourly_fall_back_fires_fold_one_only() -> None:
    """Regression: hourly must not adopt Dagster's fire-both-folds path."""
    from zoneinfo import ZoneInfo

    from backend.core.time import parse_instant
    from backend.worker.cron import ZoneCronSchedule

    tz_name = "America/Los_Angeles"
    schedule = ZoneCronSchedule("45 * * * *", schedule_timezone=tz_name)
    first = schedule._next_fire_after(parse_instant("2025-11-02T07:45:00Z"))
    local_first = first.astimezone(ZoneInfo(tz_name))
    assert (local_first.hour, local_first.minute, local_first.fold) == (1, 45, 1)

    second = schedule._next_fire_after(first)
    local_second = second.astimezone(ZoneInfo(tz_name))
    # Skip fold=0 of 01:45; next wall match is 02:45 PST.
    assert (local_second.hour, local_second.minute) == (2, 45)
