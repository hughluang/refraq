"""Data Channel System Parameters."""

from __future__ import annotations

from backend.admin.system_parameters import IntConstraint, ParameterSpec, resolve_int

__all__ = [
    "CHANNEL_PARAMETER_SPECS",
    "RUN_RECORD_INTERVAL_SECONDS",
    "RUN_RECORD_SCHEDULE_KEY",
    "RUN_RECORD_TASK_NAME",
    "channel_dataset_max_total_gb",
    "channel_dataset_retention_days",
    "channel_dataset_success_retention_hours",
    "channel_http_response_max_bytes",
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
    ParameterSpec(
        key="channel_dataset_retention_days",
        constraint=IntConstraint(minimum=1, maximum=3650),
        seed=7,
        owner="channel",
        group="data_channel",
        operator_action_required=False,
        apply_note_key="settings.parameter.channel_dataset_retention_days.apply",
        label_key="settings.parameter.channel_dataset_retention_days.label",
        help_key="settings.parameter.channel_dataset_retention_days.help",
    ),
    ParameterSpec(
        key="channel_dataset_success_retention_hours",
        constraint=IntConstraint(minimum=0, maximum=720),
        seed=24,
        owner="channel",
        group="data_channel",
        operator_action_required=False,
        apply_note_key="settings.parameter.channel_dataset_success_retention_hours.apply",
        label_key="settings.parameter.channel_dataset_success_retention_hours.label",
        help_key="settings.parameter.channel_dataset_success_retention_hours.help",
    ),
    ParameterSpec(
        key="channel_http_response_max_bytes",
        constraint=IntConstraint(minimum=65536, maximum=16777216),
        seed=1048576,
        owner="channel",
        group="data_channel",
        operator_action_required=False,
        apply_note_key="settings.parameter.channel_http_response_max_bytes.apply",
        label_key="settings.parameter.channel_http_response_max_bytes.label",
        help_key="settings.parameter.channel_http_response_max_bytes.help",
    ),
    ParameterSpec(
        key="channel_dataset_max_total_gb",
        constraint=IntConstraint(minimum=1, maximum=100000),
        seed=100,
        owner="channel",
        group="data_channel",
        operator_action_required=False,
        apply_note_key="settings.parameter.channel_dataset_max_total_gb.apply",
        label_key="settings.parameter.channel_dataset_max_total_gb.label",
        help_key="settings.parameter.channel_dataset_max_total_gb.help",
    ),
)


def channel_run_record_retention_days() -> int:
    return resolve_int("channel_run_record_retention_days").value


def channel_dataset_retention_days() -> int:
    return resolve_int("channel_dataset_retention_days").value


def channel_dataset_success_retention_hours() -> int:
    return resolve_int("channel_dataset_success_retention_hours").value


def channel_http_response_max_bytes() -> int:
    return resolve_int("channel_http_response_max_bytes").value


def channel_dataset_max_total_gb() -> int:
    return resolve_int("channel_dataset_max_total_gb").value
