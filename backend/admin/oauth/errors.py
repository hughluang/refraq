"""OAuth Client administration errors and RFC 6749 §5.2 token endpoint errors."""

from __future__ import annotations

from backend.core.errors import AppError


class OAuthClientNotFound(AppError):
    code = "OAUTH_CLIENT_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "OAuth client not found"


class OAuthClientConfigInvalid(AppError):
    code = "OAUTH_CLIENT_CONFIG_INVALID"
    http_status = 422

    def _default_message(self) -> str:
        return "OAuth client configuration is invalid"


class OAuthClientScopeForbidden(AppError):
    code = "OAUTH_CLIENT_SCOPE_FORBIDDEN"
    http_status = 409

    def _default_message(self) -> str:
        return "OAuth client allowed_scopes contains a forbidden permission"


class OAuthClientSecretUnsupported(AppError):
    code = "OAUTH_CLIENT_SECRET_UNSUPPORTED"
    http_status = 409

    def _default_message(self) -> str:
        return "Client secret rotation is only supported for secret-authenticated clients"


class OAuthTokenError(Exception):
    """RFC 6749 §5.2 OAuth error returned as JSON on /oauth/token."""

    def __init__(
        self,
        error: str,
        description: str,
        *,
        http_status: int = 400,
    ) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.http_status = http_status
