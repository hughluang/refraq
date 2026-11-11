"""Host read failures."""

from __future__ import annotations

from backend.core.errors import AppError


class HostSeriesUnavailable(AppError):
    """The series store could not be queried. Not a capacity rejection."""

    code = "HOST_SERIES_UNAVAILABLE"
    http_status = 503

    def _default_message(self) -> str:
        return "The host series could not be read."
