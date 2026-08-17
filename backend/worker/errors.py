"""Mechanism Scheduled Task errors."""

from __future__ import annotations

from backend.core.errors import AppError

__all__ = [
    "ScheduleCadenceInvalid",
    "ScheduleNotFound",
    "ScheduleRunningTimeoutInvalid",
    "ScheduleSystemImmutable",
]


class ScheduleNotFound(AppError):
    code = "SCHEDULE_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Scheduled Task not found"


class ScheduleSystemImmutable(AppError):
    code = "SCHEDULE_SYSTEM_IMMUTABLE"
    http_status = 409

    def _default_message(self) -> str:
        return "System Scheduled Tasks cannot be changed"


class ScheduleCadenceInvalid(AppError):
    code = "SCHEDULE_CADENCE_INVALID"
    http_status = 400

    def _default_message(self) -> str:
        return "Scheduled Task cadence is invalid"


class ScheduleRunningTimeoutInvalid(AppError):
    code = "SCHEDULE_RUNNING_TIMEOUT_INVALID"
    http_status = 400

    def _default_message(self) -> str:
        return "Running Time Limit must be a positive number of seconds"
