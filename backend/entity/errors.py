"""Domain errors for Business Entity."""

from __future__ import annotations

from backend.core.errors import AppError

__all__ = [
    "EntityAlreadyDeprecated",
    "EntityAlreadyPublished",
    "EntityAttributeInvalid",
    "EntityDeprecated",
    "EntityNeverPublished",
    "EntityNotFound",
    "EntityNotPublished",
    "EntityNotUnpublished",
    "EntityPublishEmpty",
    "EntityPublishing",
    "EntityReferenced",
    "EntityRequestInvalid",
    "EntityTableInService",
    "EntityTableNameDup",
    "EntityTableNameInvalid",
    "EntityVersionIdConflict",
    "EntityVersionNotFound",
    "EntityVersionSuperseded",
]


class EntityRequestInvalid(AppError):
    code = "REQUEST_INVALID"
    http_status = 422

    def _default_message(self) -> str:
        return "Request validation failed"


class EntityNotFound(AppError):
    code = "ENTITY_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Business Entity not found"


class EntityVersionNotFound(AppError):
    code = "ENTITY_VERSION_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Entity Version not found"


class EntityTableNameInvalid(AppError):
    code = "ENTITY_TABLE_NAME_INVALID"
    http_status = 422

    def _default_message(self) -> str:
        return "Business Entity table_name is invalid"


class EntityVersionIdConflict(Exception):
    """The version id primary key is already taken."""


class EntityTableNameDup(AppError):
    code = "ENTITY_TABLE_NAME_DUP"
    http_status = 409

    def _default_message(self) -> str:
        return "Business Entity table_name already exists"


class EntityAttributeInvalid(AppError):
    code = "ENTITY_ATTRIBUTE_INVALID"
    http_status = 422

    def _default_message(self) -> str:
        return "Attribute definition is invalid"


class EntityNotUnpublished(AppError):
    code = "ENTITY_NOT_UNPUBLISHED"
    http_status = 422

    def _default_message(self) -> str:
        return "Save and publish target an unpublished version"


class EntityNotPublished(AppError):
    code = "ENTITY_NOT_PUBLISHED"
    http_status = 422

    def _default_message(self) -> str:
        return "A new version opens only from a published current version"


class EntityPublishing(AppError):
    code = "ENTITY_PUBLISHING"
    http_status = 422

    def _default_message(self) -> str:
        return "A publishing version refuses writes"


class EntityPublishEmpty(AppError):
    code = "ENTITY_PUBLISH_EMPTY"
    http_status = 422

    def _default_message(self) -> str:
        return "Publish requires at least one attribute"


class EntityDeprecated(AppError):
    code = "ENTITY_DEPRECATED"
    http_status = 422

    def _default_message(self) -> str:
        return "A deprecated Business Entity refuses writes"


class EntityNeverPublished(AppError):
    code = "ENTITY_NEVER_PUBLISHED"
    http_status = 422

    def _default_message(self) -> str:
        return "Deprecate requires a published Business Entity"


class EntityAlreadyDeprecated(AppError):
    code = "ENTITY_ALREADY_DEPRECATED"
    http_status = 422

    def _default_message(self) -> str:
        return "The Business Entity is already deprecated"


class EntityAlreadyPublished(AppError):
    code = "ENTITY_ALREADY_PUBLISHED"
    http_status = 409

    def _default_message(self) -> str:
        return "A published Business Entity cannot be deleted"


class EntityReferenced(AppError):
    code = "ENTITY_REFERENCED"
    http_status = 409

    def _default_message(self) -> str:
        return (
            "A current-version Entity Reference aims at this Business Entity"
        )


class EntityVersionSuperseded(AppError):
    code = "ENTITY_VERSION_SUPERSEDED"
    http_status = 422

    def _default_message(self) -> str:
        return "Save and publish target the current version only"


class EntityTableInService(AppError):
    code = "ENTITY_TABLE_IN_SERVICE"
    http_status = 422

    def _default_message(self) -> str:
        return (
            "This table still serves the Entity; drop it after the Entity is deprecated."
            " Opening a new version does not take it out of service"
        )

