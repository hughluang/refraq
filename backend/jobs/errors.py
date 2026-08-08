"""Mechanism Job errors (platform primitive)."""

from __future__ import annotations

from backend.core.errors import AppError


class JobNotFound(AppError):
    code = "JOB_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Job not found"


class JobNotCancellable(AppError):
    code = "JOB_NOT_CANCELLABLE"
    http_status = 400

    def _default_message(self) -> str:
        return "Job is already terminal"
