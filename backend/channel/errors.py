"""Data Channel domain errors."""

from __future__ import annotations

from typing import Any

from backend.core.errors import AppError

__all__ = [
    "ChannelDraftConflict",
    "ChannelGraphInvalid",
    "ChannelNotFound",
    "ChannelNotPublished",
    "ChannelRequestInvalid",
    "ChannelRunNotFound",
    "ChannelRunNotRerunnable",
    "ChannelTriggerInvalid",
    "ChannelVariableNameInvalid",
    "ChannelVariableNotFound",
    "ChannelVersionNotFound",
    "EmailAccountInUse",
    "EmailAccountNotFound",
    "WebhookInUse",
    "WebhookNotFound",
    "WebhookUrlRejected",
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

    def extra_members(self) -> dict[str, Any]:
        return {
            "problems": [
                {
                    "code": problem.code,
                    "node_id": problem.node_id,
                    "edge_id": problem.edge_id,
                    "path": list(problem.path),
                    "detail": problem.detail,
                    "severity": problem.severity,
                }
                for problem in self.problems
            ]
        }

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
        return "Graph does not have exactly one trigger node"


class ChannelVariableNotFound(AppError):
    code = "CHANNEL_VARIABLE_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Global Variable not found"


class ChannelVariableNameInvalid(AppError):
    code = "CHANNEL_VARIABLE_NAME_INVALID"
    http_status = 422

    def _default_message(self) -> str:
        return "Global Variable name is invalid"


class ChannelRunNotFound(AppError):
    code = "CHANNEL_RUN_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Channel run not found"


class ChannelRunNotRerunnable(AppError):
    code = "CHANNEL_RUN_NOT_RERUNNABLE"
    http_status = 422

    def _default_message(self) -> str:
        return "Only a failed published run can be rerun"


class EmailAccountNotFound(AppError):
    code = "EMAIL_ACCOUNT_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Email Account not found"


class EmailAccountInUse(AppError):
    code = "EMAIL_ACCOUNT_IN_USE"
    http_status = 409

    def _default_message(self) -> str:
        return "Email Account is still referenced by a Data Channel"


class WebhookNotFound(AppError):
    code = "WEBHOOK_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Webhook not found"


class WebhookUrlRejected(AppError):
    code = "WEBHOOK_URL_REJECTED"
    http_status = 422

    def _default_message(self) -> str:
        return "Webhook URL is not allowed"


class WebhookInUse(AppError):
    code = "WEBHOOK_IN_USE"
    http_status = 409

    def _default_message(self) -> str:
        return "Webhook is still referenced by a Data Channel"


class ChannelRequestInvalid(AppError):
    code = "REQUEST_INVALID"
    http_status = 422

    def _default_message(self) -> str:
        return "Request validation failed"

