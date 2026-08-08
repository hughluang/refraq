"""Cross-package error primitive for HTTP-mappable domain failures."""

from __future__ import annotations


class AppError(Exception):
    """Base class for errors that map to an API error response."""

    code: str = "APP_ERROR"
    http_status: int = 400

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)
        self.message = message or self._default_message()

    def _default_message(self) -> str:
        return self.code
