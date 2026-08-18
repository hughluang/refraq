"""Job-owned System Parameter declarations and typed accessors."""

from __future__ import annotations

from datetime import timedelta

from backend.admin.system_parameters import IntConstraint, ParameterSpec, resolve_int
from backend.core.time import utc_now

__all__ = [
    "JOBS_PARAMETER_SPECS",
    "job_lost_detection_sec",
    "reaper_lost_detection_sec",
]

JOBS_PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        key="job_lost_detection_sec",
        constraint=IntConstraint(minimum=15, maximum=3600),
        seed=60,
        owner="jobs",
        group="jobs",
        operator_action_required=False,
        apply_note_key="settings.parameter.job_lost_detection_sec.apply",
        label_key="settings.parameter.job_lost_detection_sec.label",
        help_key="settings.parameter.job_lost_detection_sec.help",
    ),
)


def job_lost_detection_sec() -> int:
    return resolve_int("job_lost_detection_sec").value


def reaper_lost_detection_sec() -> int:
    """Effective cutoff for the reaper, including tighten grace."""
    resolved = resolve_int("job_lost_detection_sec")
    current = resolved.value
    previous = resolved.previous_value
    if previous is None or current >= previous:
        return current
    if resolved.updated_at is None:
        return current
    grace = max(5.0, previous / 3.0)
    if utc_now() < resolved.updated_at + timedelta(seconds=grace):
        return previous
    return current
