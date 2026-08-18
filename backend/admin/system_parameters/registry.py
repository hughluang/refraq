"""Assembled System Parameter registry. Frozen after composition."""

from __future__ import annotations

from collections.abc import Sequence

from backend.admin.system_parameters.errors import (
    ParameterRegistryFrozen,
    UnregisteredParameter,
)
from backend.admin.system_parameters.spec import ParameterSpec

_registry: dict[str, ParameterSpec] = {}
_group_order: tuple[str, ...] = ()
_frozen = False


def register_parameters(
    specs: Sequence[ParameterSpec],
    *,
    group_order: Sequence[str] = (),
) -> None:
    """Register specs and freeze. Re-registering the same set is a no-op."""
    global _frozen, _group_order
    incoming = {spec.key: spec for spec in specs}
    if len(incoming) != len(specs):
        raise ValueError("duplicate system parameter keys")
    order = tuple(group_order)
    if _frozen:
        if _registry != incoming or _group_order != order:
            raise ParameterRegistryFrozen()
        return
    _registry.update(incoming)
    _group_order = order
    _frozen = True


def is_registry_frozen() -> bool:
    return _frozen


def get_parameter_spec(key: str) -> ParameterSpec:
    spec = _registry.get(key)
    if spec is None:
        raise UnregisteredParameter(f"unregistered system parameter: {key}")
    return spec


def list_registered_specs() -> tuple[ParameterSpec, ...]:
    if not _frozen:
        raise UnregisteredParameter("system parameter registry is not assembled")
    return tuple(
        sorted(
            _registry.values(),
            key=lambda spec: (
                _group_order.index(spec.group) if spec.group in _group_order else 99,
                spec.key,
            ),
        )
    )


def reset_parameter_registry() -> None:
    """Test helper: unfreeze and clear the assembled registry."""
    global _frozen
    global _group_order
    _registry.clear()
    _group_order = ()
    _frozen = False
