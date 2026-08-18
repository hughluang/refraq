"""Mechanism errors for System Parameters."""

from __future__ import annotations

from backend.core.errors import AppError


class UnregisteredParameter(AppError):
    code = "SYSTEM_PARAMETER_UNREGISTERED"
    http_status = 500

    def _default_message(self) -> str:
        return "System parameter is not registered"


class ParameterValueInvalid(AppError):
    code = "SYSTEM_PARAMETER_INVALID"
    http_status = 422

    def _default_message(self) -> str:
        return "System parameter value is invalid"


class ParameterRegistryFrozen(AppError):
    code = "SYSTEM_PARAMETER_REGISTRY_FROZEN"
    http_status = 500

    def _default_message(self) -> str:
        return "System parameter registry is already assembled"


class ParameterReadFailed(AppError):
    """Catalog / strict read could not load a stored row. Consumers use last-known-good instead."""

    code = "SYSTEM_PARAMETER_READ_FAILED"
    http_status = 503

    def _default_message(self) -> str:
        return "System parameter store read failed"
