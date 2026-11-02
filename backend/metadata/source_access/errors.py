"""Problem Codes for Source Membership writes."""

from __future__ import annotations

from backend.core.errors import AppError


class SourceMembershipDuplicate(AppError):
    code = "SOURCE_MEMBERSHIP_DUPLICATE"
    http_status = 409

    def _default_message(self) -> str:
        return "A membership already exists for this subject and target"


class SourceMembershipSubjectUnknown(AppError):
    code = "SOURCE_MEMBERSHIP_SUBJECT_UNKNOWN"
    http_status = 422

    def _default_message(self) -> str:
        return "Subject does not exist"


class SourceMembershipLevelUnknown(AppError):
    code = "SOURCE_MEMBERSHIP_LEVEL_UNKNOWN"
    http_status = 422

    def _default_message(self) -> str:
        return "Unknown Source access level"
