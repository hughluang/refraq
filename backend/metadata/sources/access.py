"""Source access: interpret Connector Spec (validate / seal / project / endpoint)."""

from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator

from backend.core.secrets import SecretsDecryptError, decrypt_secret, encrypt_secret
from backend.metadata.connectors import specs as connector_specs
from backend.metadata.connectors.base import SourceEndpoint
from backend.metadata.errors import (
    SourceAccessInvalid,
    SourceEngineUnsupported,
    SourceSecretRequired,
)

SUPPORTED_ENGINES = connector_specs.SUPPORTED_ENGINES

_SCOPE_CATALOG = "catalog"
_SCOPE_SCHEMA = "schema"

__all__ = [
    "SUPPORTED_ENGINES",
    "validate_access",
    "seal_access",
    "encrypt_access_blob",
    "decrypt_access_blob",
    "project_access",
    "endpoint_from_access",
]


def validate_access(engine: str, access: dict[str, Any] | None) -> dict[str, Any]:
    if engine not in SUPPORTED_ENGINES:
        raise SourceEngineUnsupported()
    if not isinstance(access, dict):
        raise SourceAccessInvalid("access must be an object")
    schema = connector_specs.get_connector_spec(engine)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(access), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        path = ".".join(str(p) for p in first.absolute_path) or "(root)"
        raise SourceAccessInvalid(f"{path}: {first.message}")
    return access


def encrypt_access_blob(access: dict[str, Any]) -> str:
    payload = json.dumps(access, separators=(",", ":"), ensure_ascii=False)
    return encrypt_secret(payload)


def seal_access(engine: str, access: dict[str, Any] | None) -> str:
    """Validate access against Connector Spec and return ciphertext."""
    return encrypt_access_blob(validate_access(engine, access))


def decrypt_access_blob(ciphertext: str) -> dict[str, Any]:
    try:
        raw = decrypt_secret(ciphertext)
    except SecretsDecryptError as exc:
        raise SourceSecretRequired(f"Access decrypt failed: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SourceSecretRequired(f"Access blob is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SourceSecretRequired("Access blob must be a JSON object")
    return data


def project_access(engine: str, access: dict[str, Any]) -> dict[str, Any]:
    """Access with x-secret fields removed for read APIs."""
    spec = connector_specs.get_connector_spec(engine)
    secret_keys = connector_specs.iter_secret_keys(spec)
    return {k: v for k, v in access.items() if k not in secret_keys}


def endpoint_from_access(
    *,
    engine: str,
    access: dict[str, Any],
) -> SourceEndpoint:
    """Assemble SourceEndpoint from a Spec-validated access document."""
    catalog_key, schema_key = _scope_keys_from_spec(
        engine, connector_specs.get_connector_spec(engine)
    )
    extra_raw = access.get("extra") or {}
    extra = {
        str(k): str(v)
        for k, v in extra_raw.items()
        if isinstance(k, str) and v is not None
    }
    root = access.get("ssl_root_cert")
    client_cert = access.get("ssl_client_cert")
    client_key = access.get("ssl_client_key")
    return SourceEndpoint(
        engine=engine,
        host=str(access["host"]),
        port=int(access["port"]),
        username=str(access["username"]),
        password=str(access["password"]),
        database_name=_required_scope_value(access, catalog_key),
        schema_filter=_required_scope_value(access, schema_key),
        ssl_mode=str(access.get("ssl_mode") or "require"),
        ssl_root_cert=str(root) if root else None,
        ssl_client_cert=str(client_cert) if client_cert else None,
        ssl_client_key=str(client_key) if client_key else None,
        extra=extra,
    )


def _scope_keys_from_spec(engine: str, spec: dict[str, Any]) -> tuple[str, str]:
    catalog_key: str | None = None
    schema_key: str | None = None
    props = spec.get("properties") or {}
    for name, prop in props.items():
        if not isinstance(prop, dict):
            continue
        role = prop.get("x-scope")
        if role == _SCOPE_CATALOG:
            if catalog_key is not None:
                raise RuntimeError(
                    f"Connector Spec for {engine} has multiple x-scope=catalog properties"
                )
            catalog_key = name
        elif role == _SCOPE_SCHEMA:
            if schema_key is not None:
                raise RuntimeError(
                    f"Connector Spec for {engine} has multiple x-scope=schema properties"
                )
            schema_key = name
        elif role is not None:
            raise RuntimeError(
                f"Connector Spec for {engine} has unknown x-scope={role!r} on {name}"
            )
    if catalog_key is None or schema_key is None:
        raise RuntimeError(
            f"Connector Spec for {engine} must mark x-scope catalog and schema"
        )
    return catalog_key, schema_key


def _required_scope_value(access: dict[str, Any], key: str) -> str:
    value = access.get(key)
    if not value:
        raise SourceAccessInvalid(f"access.{key} is required")
    return str(value)
