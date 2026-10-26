"""Tag vocabulary errors."""

from __future__ import annotations

from backend.core.errors import AppError

__all__ = [
    "TagDescriptionInvalid",
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
