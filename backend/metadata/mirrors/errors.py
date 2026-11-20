"""Application errors shared by Mirror services and stores."""

from backend.core.errors import AppError


class MirrorError(AppError):
    def __init__(self, code, status):
        self.code = code
        self.http_status = status
        super().__init__()
