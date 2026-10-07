"""User Group and Subject Attribute errors."""

from __future__ import annotations

from backend.core.errors import AppError


class SubjectError(AppError):
    code = "SUBJECT_ERROR"
    http_status = 422


class UserGroupNotFound(SubjectError):
    code = "USER_GROUP_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "User Group not found"


class UserGroupKeyDuplicate(SubjectError):
    code = "USER_GROUP_KEY_DUPLICATE"
    http_status = 409

    def _default_message(self) -> str:
        return "User Group key already exists"


class UserGroupInvalid(SubjectError):
    code = "USER_GROUP_INVALID"
    http_status = 422

    def _default_message(self) -> str:
        return "User Group is invalid"


class SubjectAttributeNotFound(SubjectError):
    code = "SUBJECT_ATTRIBUTE_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Subject Attribute not found"


class SubjectAttributeKeyDuplicate(SubjectError):
    code = "SUBJECT_ATTRIBUTE_KEY_DUPLICATE"
    http_status = 409

    def _default_message(self) -> str:
        return "Subject Attribute key already exists"


class SubjectAttributeInvalid(SubjectError):
    code = "SUBJECT_ATTRIBUTE_INVALID"
    http_status = 422

    def _default_message(self) -> str:
        return "Subject Attribute is invalid"
