"""Metadata-owned System Parameter declarations and typed accessors."""

from __future__ import annotations

from backend.admin.system_parameters import IntConstraint, ParameterSpec, resolve_int

__all__ = [
    "METADATA_PARAMETER_SPECS",
    "QUERY_TIMEOUT_SEC_MAX",
    "query_max_rows",
    "query_timeout_sec",
]

QUERY_TIMEOUT_SEC_MAX = 3600

METADATA_PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        key="query_timeout_sec",
        constraint=IntConstraint(minimum=5, maximum=QUERY_TIMEOUT_SEC_MAX),
        seed=30,
        owner="metadata",
        group="query",
        operator_action_required=False,
        apply_note_key="settings.parameter.query_timeout_sec.apply",
        label_key="settings.parameter.query_timeout_sec.label",
        help_key="settings.parameter.query_timeout_sec.help",
    ),
    ParameterSpec(
        key="query_max_rows",
        constraint=IntConstraint(minimum=100, maximum=10_000),
        seed=1000,
        owner="metadata",
        group="query",
        operator_action_required=False,
        apply_note_key="settings.parameter.query_max_rows.apply",
        label_key="settings.parameter.query_max_rows.label",
        help_key="settings.parameter.query_max_rows.help",
    ),
)


def query_timeout_sec() -> int:
    return resolve_int("query_timeout_sec").value


def query_max_rows() -> int:
    return resolve_int("query_max_rows").value
