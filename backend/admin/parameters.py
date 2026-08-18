"""Admin-owned System Parameter declarations and typed accessors."""

from __future__ import annotations

from backend.admin.system_parameters import IntConstraint, ParameterSpec, resolve_int

__all__ = [
    "ADMIN_PARAMETER_SPECS",
    "admin_session_ttl_hours",
]

ADMIN_PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        key="admin_session_ttl_hours",
        constraint=IntConstraint(minimum=1, maximum=168),
        seed=8,
        owner="admin",
        group="session",
        operator_action_required=False,
        apply_note_key="settings.parameter.admin_session_ttl_hours.apply",
        label_key="settings.parameter.admin_session_ttl_hours.label",
        help_key="settings.parameter.admin_session_ttl_hours.help",
    ),
)


def admin_session_ttl_hours() -> int:
    return resolve_int("admin_session_ttl_hours").value
