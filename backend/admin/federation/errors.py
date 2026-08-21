"""Federated authentication errors."""

from __future__ import annotations

from backend.core.errors import AppError


class FederationError(AppError):
    code = "FEDERATION_ERROR"
    http_status = 400


class ProviderNotFound(FederationError):
    code = "IDENTITY_PROVIDER_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Identity provider not found"


class ProviderConfigInvalid(FederationError):
    code = "IDENTITY_PROVIDER_INVALID_CONFIG"
    http_status = 400

    def _default_message(self) -> str:
        return "Identity provider configuration is invalid"


class ProviderProtocolUnsupported(FederationError):
    code = "IDENTITY_PROVIDER_PROTOCOL_UNSUPPORTED"
    http_status = 400

    def _default_message(self) -> str:
        return "Identity provider protocol is not supported"


class ProviderIssuerDuplicate(FederationError):
    code = "IDENTITY_PROVIDER_ISSUER_DUPLICATE"
    http_status = 409

    def _default_message(self) -> str:
        return "An identity provider with this issuer already exists"


class ProviderIssuerImmutable(FederationError):
    code = "IDENTITY_PROVIDER_ISSUER_IMMUTABLE"
    http_status = 409

    def _default_message(self) -> str:
        return "Issuer cannot be changed after the identity provider is created"


class ProviderDefaultRoleForbidden(FederationError):
    code = "IDENTITY_PROVIDER_DEFAULT_ROLE_FORBIDDEN"
    http_status = 409

    def _default_message(self) -> str:
        return "This Role cannot be used as an auto-provisioning default"


class SsoProviderUnavailable(FederationError):
    code = "AUTH_SSO_PROVIDER_UNAVAILABLE"
    http_status = 503

    def _default_message(self) -> str:
        return "Identity provider is unavailable"


class SsoHandoffInvalid(FederationError):
    code = "AUTH_SSO_HANDOFF_INVALID"
    http_status = 400

    def _default_message(self) -> str:
        return "Federated login state is invalid or expired"


class SsoAssertionRejected(FederationError):
    code = "AUTH_SSO_ASSERTION_REJECTED"
    http_status = 401

    def _default_message(self) -> str:
        return "Identity token is invalid"


class SsoNotAdmitted(FederationError):
    code = "AUTH_SSO_NOT_ADMITTED"
    http_status = 403

    def _default_message(self) -> str:
        return "Federated sign-in is not admitted"


class PendingIdentityNotFound(FederationError):
    code = "PENDING_IDENTITY_NOT_FOUND"
    http_status = 404

    def _default_message(self) -> str:
        return "Pending identity not found"


class PendingIdentityExpired(FederationError):
    code = "PENDING_IDENTITY_EXPIRED"
    http_status = 404

    def _default_message(self) -> str:
        return "Pending identity has expired"


class FederationAlreadyBound(FederationError):
    code = "FEDERATION_ALREADY_BOUND"
    http_status = 409

    def _default_message(self) -> str:
        return "This User already has an external identity binding"


class FederationNotBound(FederationError):
    code = "FEDERATION_NOT_BOUND"
    http_status = 409

    def _default_message(self) -> str:
        return "This User has no external identity binding"


class FederationPasswordRequired(FederationError):
    code = "FEDERATION_PASSWORD_REQUIRED"
    http_status = 400

    def _default_message(self) -> str:
        return "An initial local password is required"


class FederationLastLocalSuperAdmin(FederationError):
    code = "FEDERATION_LAST_LOCAL_SUPER_ADMIN"
    http_status = 409

    def _default_message(self) -> str:
        return "The last local active super admin cannot be converted to OIDC"
