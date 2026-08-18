"""Published System Parameter mechanism. Generic keys and values only."""

from __future__ import annotations

from backend.admin.system_parameters.errors import (
    ParameterReadFailed,
    ParameterRegistryFrozen,
    ParameterValueInvalid,
    UnregisteredParameter,
)
from backend.admin.system_parameters.registry import (
    get_parameter_spec,
    is_registry_frozen,
    list_registered_specs,
    register_parameters,
    reset_parameter_registry,
)
from backend.admin.system_parameters.resolver import (
    ResolvedIntParameter,
    ResolvedParameter,
    clear_last_known,
    occupy_registered_parameters,
    read_stored_parameter,
    reset_parameter,
    resolve_int,
    set_parameter,
    validate_parameter_write,
)
from backend.admin.system_parameters.spec import (
    JSON_SCHEMA_PROFILE_KEYWORDS,
    IntConstraint,
    ParameterSource,
    ParameterSpec,
    ParameterValue,
)
from backend.admin.system_parameters.store import (
    ParameterRecord,
    get_parameter_store,
    reset_parameter_store,
)


def reset_system_parameters() -> None:
    """Test helper: clear store and last-known-good; re-occupy if already assembled."""
    reset_parameter_store()
    clear_last_known()
    if is_registry_frozen():
        occupy_registered_parameters()

__all__ = [
    "JSON_SCHEMA_PROFILE_KEYWORDS",
    "IntConstraint",
    "ParameterReadFailed",
    "ParameterRegistryFrozen",
    "ParameterSource",
    "ParameterSpec",
    "ParameterValue",
    "ParameterRecord",
    "ParameterValueInvalid",
    "ResolvedIntParameter",
    "ResolvedParameter",
    "UnregisteredParameter",
    "clear_last_known",
    "get_parameter_spec",
    "get_parameter_store",
    "is_registry_frozen",
    "list_registered_specs",
    "occupy_registered_parameters",
    "read_stored_parameter",
    "register_parameters",
    "reset_parameter",
    "reset_parameter_registry",
    "reset_parameter_store",
    "reset_system_parameters",
    "resolve_int",
    "set_parameter",
    "validate_parameter_write",
]
