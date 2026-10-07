"""Entity-owned System Parameter declarations and typed accessors.

Keys stay flat snake_case, matching the registry. The implementation plan's
dotted names are not registered.
"""

from __future__ import annotations

from backend.admin.system_parameters import IntConstraint, ParameterSpec, resolve_int

__all__ = [
    "ENTITY_PARAMETER_SPECS",
    "access_log_retention_days",
    "max_profile_combinations",
]

ENTITY_PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        key="max_profile_combinations",
        constraint=IntConstraint(minimum=1, maximum=1024),
        seed=64,
        owner="entity",
        group="entity_access",
        operator_action_required=False,
        apply_note_key="settings.parameter.max_profile_combinations.apply",
        label_key="settings.parameter.max_profile_combinations.label",
        help_key="settings.parameter.max_profile_combinations.help",
    ),
    ParameterSpec(
        key="access_log_retention_days",
        constraint=IntConstraint(minimum=7, maximum=3650),
        seed=90,
        owner="entity",
        group="entity_access",
        operator_action_required=False,
        apply_note_key="settings.parameter.access_log_retention_days.apply",
        label_key="settings.parameter.access_log_retention_days.label",
        help_key="settings.parameter.access_log_retention_days.help",
    ),
)


def max_profile_combinations() -> int:
    return resolve_int("max_profile_combinations").value


def access_log_retention_days() -> int:
    return resolve_int("access_log_retention_days").value
