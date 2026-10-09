"""Data Channel domain errors."""

from __future__ import annotations

from backend.core.errors import AppError

__all__ = [
    "ChannelDraftConflict",
    "ChannelGraphInvalid",
    "ChannelNotFound",
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

    def _default_message(self) -> str:
        return "Draft graph is invalid"

