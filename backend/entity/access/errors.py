"""Entity access-control errors."""

from __future__ import annotations

from backend.core.errors import RETRY_AFTER_DEFAULT_SEC, AppError

__all__ = [
    "EntityAccessCombinationLimit",
    "EntityAccessGrantNotFound",
    "EntityAccessInUse",
    "EntityAccessInvalid",
    "EntityAccessKeyDup",
    "EntityAccessPending",
    "EntityAccessProfileNotFound",
    "EntityAccessRestrictionNotFound",
    "EntityAccessWriteDenied",
]


class EntityAccessInvalid(AppError):
    code = "ENTITY_ACCESS_INVALID"
    http_status = 422

    def _default_message(self) -> str:
        return "Entity access policy is invalid"


class EntityAccessProfileNotFound(AppError):
    code = "ENTITY_ACCESS_PROFILE_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Access profile not found"


class EntityAccessGrantNotFound(AppError):
    code = "ENTITY_ACCESS_GRANT_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Access grant not found"


class EntityAccessRestrictionNotFound(AppError):
    code = "ENTITY_ACCESS_RESTRICTION_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Access restriction not found"


class EntityAccessKeyDup(AppError):
    code = "ENTITY_ACCESS_KEY_DUP"
    http_status = 409

    def _default_message(self) -> str:
        return "Access profile key already exists on this Entity"


class EntityAccessInUse(AppError):
    code = "ENTITY_ACCESS_IN_USE"
    http_status = 409

    def _default_message(self) -> str:
        return "Entity access object is still referenced"


class EntityAccessPending(AppError):
    code = "ENTITY_ACCESS_PENDING"
    http_status = 503
    retry_after_sec = RETRY_AFTER_DEFAULT_SEC

    def _default_message(self) -> str:
        return "access configuration generating"


class EntityAccessWriteDenied(AppError):
    code = "ENTITY_ACCESS_WRITE_DENIED"
    http_status = 403

    def _default_message(self) -> str:
        return "No single grant allows this write"


class EntityAccessCombinationLimit(AppError):
    code = "ENTITY_ACCESS_COMBINATION_LIMIT"
    http_status = 409

    def _default_message(self) -> str:
        return "Access configuration over limit"
