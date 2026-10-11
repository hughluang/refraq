"""Data Channel System Parameters."""

from __future__ import annotations

from backend.admin.system_parameters import IntConstraint, ParameterSpec

__all__ = ["CHANNEL_PARAMETER_SPECS"]

CHANNEL_PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        key="channel_run_record_retention_days",
        constraint=IntConstraint(minimum=1, maximum=3650),
        seed=30,
        owner="channel",
        group="data_channel",
        operator_action_required=False,
        apply_note_key="settings.parameter.channel_run_record_retention_days.apply",
        label_key="settings.parameter.channel_run_record_retention_days.label",
        help_key="settings.parameter.channel_run_record_retention_days.help",
    ),
)
