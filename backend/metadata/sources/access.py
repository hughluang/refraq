"""Per-engine Source access JSON validation via Connector Spec."""

from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator

from backend.core.secrets import SecretsDecryptError, decrypt_secret, encrypt_secret
from backend.metadata.connectors.specs import (
    SUPPORTED_ENGINES,
    get_connector_spec,
    project_access,
)
from backend.metadata.errors import (
    SourceAccessInvalid,
    SourceEngineUnsupported,
    SourceSecretRequired,
)

# Re-export for existing imports
__all__ = [
    "SUPPORTED_ENGINES",
    "validate_access",
    "seal_access",
    "encrypt_access_blob",
    "decrypt_access_blob",
    "project_access",
]


def validate_access(engine: str, access: dict[str, Any] | None) -> dict[str, Any]:
    if engine not in SUPPORTED_ENGINES:
        raise SourceEngineUnsupported()
    if not isinstance(access, dict):
        raise SourceAccessInvalid("access must be an object")
    schema = get_connector_spec(engine)
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
