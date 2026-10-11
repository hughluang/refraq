"""Data Channel domain errors."""

from __future__ import annotations

from backend.core.errors import AppError

__all__ = [
    "ChannelDraftConflict",
    "ChannelGraphInvalid",
    "ChannelNotFound",
    "ChannelNotPublished",
    "ChannelRunNotFound",
    "ChannelTriggerInvalid",
    "ChannelVersionNotFound",
]


class ChannelNotFound(AppError):
    code = "CHANNEL_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Data Channel not found"


class ChannelVersionNotFound(AppError):
    code = "CHANNEL_VERSION_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Channel Version not found"


class ChannelDraftConflict(AppError):
    code = "CHANNEL_DRAFT_CONFLICT"
    http_status = 409

    def _default_message(self) -> str:
        return "Draft revision does not match the stored draft"


class ChannelGraphInvalid(AppError):
    code = "CHANNEL_GRAPH_INVALID"
    http_status = 422

    def __init__(self, message: str | None = None, *, problems: list | None = None) -> None:
        super().__init__(message)
        self.problems = problems or []

    def _default_message(self) -> str:
        return "Draft graph is invalid"


class ChannelNotPublished(AppError):
    code = "CHANNEL_NOT_PUBLISHED"
    http_status = 409

    def _default_message(self) -> str:
        return "Data Channel has no published version"


class ChannelTriggerInvalid(AppError):
    code = "CHANNEL_TRIGGER_INVALID"
    http_status = 422

    def _default_message(self) -> str:
        return "Manual trigger node is missing or ambiguous"


class ChannelRunNotFound(AppError):
    code = "CHANNEL_RUN_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Channel run not found"

