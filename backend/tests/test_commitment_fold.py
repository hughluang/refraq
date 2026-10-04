"""Cron commitment zones fold into one schedule_timezone row."""

from __future__ import annotations

import pytest

from backend.worker.commitment_fold import (
    CommitmentZonesDisagree,
    parameter_row_for_commitment_zones,
)


def test_no_cron_zones_leaves_the_parameter_absent() -> None:
    assert parameter_row_for_commitment_zones([], parameter_present=False) is None


def test_unanimous_utc_is_a_seed_row() -> None:
    assert parameter_row_for_commitment_zones(
        ["UTC", "UTC"], parameter_present=False
    ) == ("UTC", "seed")


def test_unanimous_non_utc_is_a_user_row() -> None:
    assert parameter_row_for_commitment_zones(
        ["Asia/Shanghai", "Asia/Shanghai"], parameter_present=False
    ) == ("Asia/Shanghai", "user")


def test_alias_and_current_id_fold_to_one_user_row() -> None:
    assert parameter_row_for_commitment_zones(
        ["Asia/Calcutta", "Asia/Kolkata"], parameter_present=False
    ) == ("Asia/Kolkata", "user")


def test_existing_parameter_row_is_not_replaced() -> None:
    assert (
        parameter_row_for_commitment_zones(["Asia/Shanghai"], parameter_present=True)
        is None
    )


def test_mixed_zones_fail() -> None:
    with pytest.raises(CommitmentZonesDisagree, match="Asia/Shanghai") as raised:
        parameter_row_for_commitment_zones(
            ["UTC", "Asia/Shanghai"], parameter_present=False
        )
    assert "UTC" in str(raised.value)


def test_unrecognized_zone_fails() -> None:
    with pytest.raises(CommitmentZonesDisagree, match="Not/AZone"):
        parameter_row_for_commitment_zones(["UTC", "Not/AZone"], parameter_present=True)
