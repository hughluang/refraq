"""Application errors shared by Mirror services and stores."""

from backend.core.errors import AppError


class MirrorError(AppError):
    def __init__(self, code, status):
        self.code = code
        self.http_status = status
        super().__init__()


def reject(code, status=409):
    """Raise the Mirror error for a refused request or a contradicted evidence check."""
    raise MirrorError(code, status)
