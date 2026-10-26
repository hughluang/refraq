"""Tag vocabulary errors."""

from __future__ import annotations

from typing import Any

from backend.core.errors import AppError

__all__ = [
    "SavedFilterLimit",
    "SavedFilterNameConflict",
    "SavedFilterNameInvalid",
    "SavedFilterNotFound",
    "SavedFilterRequestInvalid",
    "TagAssignmentConflict",
    "TagDescriptionInvalid",
    "TagInUse",
    "TagLimitExceeded",
    "TagNameConflict",
    "TagNameInvalid",
    "TagNotFound",
]


class TagNotFound(AppError):
    code = "TAG_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Tag not found"


class TagNameInvalid(AppError):
    code = "TAG_NAME_INVALID"
    http_status = 422

    def _default_message(self) -> str:
        return "Tag name is not valid"


class TagNameConflict(AppError):
    code = "TAG_NAME_CONFLICT"
    http_status = 409

    def _default_message(self) -> str:
        return "A Tag with this name already exists"


class TagDescriptionInvalid(AppError):
    code = "TAG_DESCRIPTION_INVALID"
    http_status = 422

    def _default_message(self) -> str:
        return "Tag description is not valid"


class TagInUse(AppError):
    """Delete refused while any subject still carries the Tag."""

    code = "TAG_IN_USE"
    http_status = 409

    def __init__(self, entity_count: int, channel_count: int) -> None:
        super().__init__()
        self.entity_count = entity_count
        self.channel_count = channel_count

    def extra_members(self) -> dict[str, Any]:
        return {
            "entity_count": self.entity_count,
            "channel_count": self.channel_count,
        }

    def _default_message(self) -> str:
        return "Tag is still assigned"


class TagLimitExceeded(AppError):
    """The resulting set would pass ten Tags."""

    code = "TAG_LIMIT_EXCEEDED"
    http_status = 422

    def __init__(self, subjects: list[dict[str, str]]) -> None:
        super().__init__()
        self.subjects = subjects

    def extra_members(self) -> dict[str, Any]:
        return {"subjects": self.subjects}

    def _default_message(self) -> str:
        return "A record can carry at most ten Tags"


class TagAssignmentConflict(AppError):
    code = "TAG_ASSIGNMENT_CONFLICT"
    http_status = 409

    def _default_message(self) -> str:
        return "Tag revision does not match the stored revision"


class SavedFilterNotFound(AppError):
    code = "SAVED_FILTER_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Saved filter not found"


class SavedFilterNameInvalid(AppError):
    code = "SAVED_FILTER_NAME_INVALID"
    http_status = 422

    def _default_message(self) -> str:
        return "Saved filter name is not valid"


class SavedFilterNameConflict(AppError):
    code = "SAVED_FILTER_NAME_CONFLICT"
    http_status = 409

    def _default_message(self) -> str:
        return "A saved filter with this name already exists"


class SavedFilterLimit(AppError):
    code = "SAVED_FILTER_LIMIT"
    http_status = 422

    def _default_message(self) -> str:
        return "A list can keep at most 20 saved filters"


class SavedFilterRequestInvalid(AppError):
    code = "REQUEST_INVALID"
    http_status = 422

    def _default_message(self) -> str:
        return "Request validation failed"
