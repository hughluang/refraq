"""Data Channel System Parameters."""

from __future__ import annotations

from backend.admin.system_parameters import IntConstraint, ParameterSpec, resolve_int

__all__ = [
    "CHANNEL_PARAMETER_SPECS",
    "RUN_RECORD_INTERVAL_SECONDS",
    "RUN_RECORD_SCHEDULE_KEY",
    "RUN_RECORD_TASK_NAME",
    "channel_run_record_retention_days",
]

# Hidden system Scheduled Task. Hourly, in code, not a System Parameter.
RUN_RECORD_SCHEDULE_KEY = "channel_run_record_retention"
RUN_RECORD_TASK_NAME = "backend.channel.tasks.purge_run_records"
RUN_RECORD_INTERVAL_SECONDS = 3600

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


def channel_run_record_retention_days() -> int:
    return resolve_int("channel_run_record_retention_days").value
