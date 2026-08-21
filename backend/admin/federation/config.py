"""Sealed Identity Provider configuration."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from jsonschema import Draft202012Validator

from backend.admin.federation.errors import (
    ProviderConfigInvalid,
    ProviderDefaultRoleForbidden,
    ProviderProtocolUnsupported,
)
from backend.admin.federation.spec import (
    OIDC_PROTOCOL_SPEC,
    OidcConfig,
    ProviderRecord,
    SUPPORTED_PROTOCOLS,
)
from backend.admin.permissions import GRANTING_PERMISSIONS
from backend.admin.role_store import RoleRecord, RoleStore
from backend.admin.roles import effective_permissions
from backend.core.secrets import SecretsDecryptError, decrypt_secret, encrypt_secret


def protocol_spec(protocol: str) -> dict[str, Any]:
    if protocol not in SUPPORTED_PROTOCOLS:
        raise ProviderProtocolUnsupported()
    return OIDC_PROTOCOL_SPEC


def normalize_issuer(issuer: str) -> str:
    value = issuer.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ProviderConfigInvalid("Issuer must be an absolute http(s) URL")
    if parsed.query or parsed.fragment:
        raise ProviderConfigInvalid("Issuer must not include a query or fragment")
    if parsed.path.endswith("/") and parsed.path != "/":
        raise ProviderConfigInvalid("Issuer must not have a trailing slash")
    if value.endswith("/") and parsed.path == "/":
        raise ProviderConfigInvalid("Issuer must not have a trailing slash")
    return value


def _validate_oidc_document(config: dict[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(OIDC_PROTOCOL_SPEC).iter_errors(config),
        key=lambda err: list(err.path),
    )
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.absolute_path) or "(root)"
        raise ProviderConfigInvalid(f"{path}: {first.message}")


def parse_oidc_config(data: dict[str, Any]) -> OidcConfig:
    document = {key: value for key, value in data.items() if value is not None}
    _validate_oidc_document(document)
    config = OidcConfig.from_dict(document)
    config.issuer = normalize_issuer(config.issuer)
    if "openid" not in config.scopes:
        raise ProviderConfigInvalid("Scopes must include openid")
    if "offline_access" in config.scopes:
        raise ProviderConfigInvalid("Scopes must not include offline_access")
    if config.auto_provision:
        if not config.default_role_id:
            raise ProviderConfigInvalid("auto_provision requires default_role_id")
        if not config.group_allowlist:
            raise ProviderConfigInvalid("auto_provision requires group_allowlist")
    if not config.client_secret:
        raise ProviderConfigInvalid("client_secret is required")
    return config


def validate_default_role(role: RoleRecord | None) -> None:
    if role is None:
        raise ProviderConfigInvalid("Configured default Role does not exist")
    if GRANTING_PERMISSIONS.intersection(effective_permissions(role)):
        raise ProviderDefaultRoleForbidden()


def validate_provider_config(config: OidcConfig, roles: RoleStore) -> None:
    if not config.auto_provision:
        return
    validate_default_role(roles.get_by_id(config.default_role_id) if config.default_role_id else None)


def encrypt_config(config: OidcConfig) -> str:
    payload = json.dumps(config.to_dict(), separators=(",", ":"), ensure_ascii=False)
    return encrypt_secret(payload)


def decrypt_config(ciphertext: str) -> OidcConfig:
    try:
        raw = decrypt_secret(ciphertext)
    except SecretsDecryptError as exc:
        raise ProviderConfigInvalid("Provider configuration cannot be decrypted") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderConfigInvalid("Provider configuration is not valid JSON") from exc
    if not isinstance(data, dict):
        raise ProviderConfigInvalid("Provider configuration must be an object")
    return OidcConfig.from_dict(data)


def validate_role_not_default_for_providers(
    role: RoleRecord, providers: list[ProviderRecord]
) -> None:
    if not GRANTING_PERMISSIONS.intersection(effective_permissions(role)):
        return
    if any(item.config.default_role_id == role.id for item in providers):
        raise ProviderDefaultRoleForbidden()
