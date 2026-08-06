"""Domain exceptions for the refraq Management Foundation auth slice."""

from __future__ import annotations


class AuthError(Exception):
    """Base class for auth-related domain errors."""

    code: str = "AUTH_ERROR"
    http_status: int = 400

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)
        self.message = message or self._default_message()

    def _default_message(self) -> str:
        return self.code


class AuthInvalidCredentials(AuthError):
    code = "AUTH_INVALID_CREDENTIALS"
    http_status = 401

    def _default_message(self) -> str:
        return "Invalid account or password"


class AuthAccountDisabled(AuthError):
    code = "AUTH_ACCOUNT_DISABLED"
    http_status = 403

    def _default_message(self) -> str:
        return "This account is disabled"


class AuthConsoleAccessRequired(AuthError):
    code = "AUTH_CONSOLE_ACCESS_REQUIRED"
    http_status = 403

    def _default_message(self) -> str:
        return "This account cannot sign in to the console"


class AuthUnauthenticated(AuthError):
    code = "AUTH_UNAUTHENTICATED"
    http_status = 401

    def _default_message(self) -> str:
        return "Not signed in or session expired"


class AuthForbidden(AuthError):
    code = "AUTH_FORBIDDEN"
    http_status = 403

    def _default_message(self) -> str:
        return "You do not have permission for this action"


class AuthPatInvalid(AuthError):
    code = "AUTH_PAT_INVALID"
    http_status = 401

    def _default_message(self) -> str:
        return "Invalid, expired, or revoked personal access token"


class TokenNotFound(AuthError):
    code = "TOKEN_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Token not found"


class TokenInvalidExpiresAt(AuthError):
    code = "TOKEN_INVALID_EXPIRES_AT"
    http_status = 400

    def _default_message(self) -> str:
        return "expires_at must be in the future"


class AuditEventNotFound(AuthError):
    code = "AUDIT_EVENT_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Audit event not found"


class UserAccountDuplicate(AuthError):
    code = "USER_ACCOUNT_DUPLICATE"
    http_status = 409

    def _default_message(self) -> str:
        return "Account already exists"


class UserInvalidRole(AuthError):
    code = "USER_INVALID_ROLE"
    http_status = 400

    def _default_message(self) -> str:
        return "Invalid role"


class UserInvalidStatus(AuthError):
    code = "USER_INVALID_STATUS"
    http_status = 400

    def _default_message(self) -> str:
        return "Invalid status"


class UserSelfDisableForbidden(AuthError):
    code = "USER_SELF_DISABLE_FORBIDDEN"
    http_status = 403

    def _default_message(self) -> str:
        return "You cannot disable your own account"


class UserNotFound(AuthError):
    code = "USER_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "User not found"


class RoleInvalidKey(AuthError):
    code = "ROLE_INVALID_KEY"
    http_status = 400

    def _default_message(self) -> str:
        return "Invalid role key"


class RoleInvalidPermission(AuthError):
    code = "ROLE_INVALID_PERMISSION"
    http_status = 400

    def _default_message(self) -> str:
        return "Permission is not in the catalog"


class RoleKeyDuplicate(AuthError):
    code = "ROLE_KEY_DUPLICATE"
    http_status = 409

    def _default_message(self) -> str:
        return "Role key already exists"


class RoleLocked(AuthError):
    code = "ROLE_LOCKED"
    http_status = 403

    def _default_message(self) -> str:
        return "System roles cannot be modified or deleted"


class RoleInUse(AuthError):
    code = "ROLE_IN_USE"
    http_status = 409

    def _default_message(self) -> str:
        return "Role is still assigned to users and cannot be deleted"


class RoleNotFound(AuthError):
    code = "ROLE_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Role not found"
