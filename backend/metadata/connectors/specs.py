"""Connector Spec (JSON Schema) — source of truth for access validation and SpecTree."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from backend.metadata.errors import SourceEngineUnsupported

SSL_MODE_ENUM_POSTGRES = ["disable", "require", "verify-ca", "verify-full"]
# Slice A: only PostgreSQL wires TLS connect_args; other engines accept disable only.
SSL_MODE_ENUM_PLAIN = ["disable"]

_EXTRA_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Driver extension key/value pairs (string values only).",
    "default": {},
    "additionalProperties": {"type": "string", "maxLength": 1024},
    "propertyNames": {"type": "string", "minLength": 1, "maxLength": 128},
}


def _base_properties(
    *,
    default_port: int,
    ssl_modes: list[str],
    default_ssl_mode: str,
    include_cert_fields: bool,
) -> dict[str, Any]:
    props: dict[str, Any] = {
        "host": {
            "type": "string",
            "minLength": 1,
            "maxLength": 512,
            "description": "Hostname or IP",
        },
        "port": {
            "type": "integer",
            "minimum": 1,
            "maximum": 65535,
            "default": default_port,
            "description": f"Default {default_port}",
        },
        "username": {
            "type": "string",
            "minLength": 1,
            "maxLength": 256,
            "description": "Database username",
        },
        "password": {
            "type": "string",
            "minLength": 1,
            "description": "Database password",
            "x-secret": True,
        },
        "ssl_mode": {
            "type": "string",
            "enum": list(ssl_modes),
            "default": default_ssl_mode,
            "description": (
                "TLS mode; verify-* may need CA / client cert fields"
                if include_cert_fields
                else "TLS not wired for this engine in slice A; only disable"
            ),
        },
        "extra": deepcopy(_EXTRA_SCHEMA),
    }
    if include_cert_fields:
        props["ssl_root_cert"] = {
            "type": "string",
            "description": "PEM root CA (when ssl_mode is verify-ca or verify-full)",
            "x-secret": True,
        }
        props["ssl_client_cert"] = {
            "type": "string",
            "description": "PEM client certificate for mTLS",
        }
        props["ssl_client_key"] = {
            "type": "string",
            "description": "PEM client private key for mTLS",
            "x-secret": True,
        }
    return props


_DATABASE_PROP: dict[str, Any] = {
    "type": "string",
    "minLength": 1,
    "maxLength": 256,
    "description": "Database name (DSN catalog + collection scope)",
}


def _schema_prop(*, default: str) -> dict[str, Any]:
    """Required schema/owner-equivalent scope; default is engine-conventional only."""
    return {
        "type": "string",
        "minLength": 1,
        "maxLength": 256,
        "default": default,
        "description": (
            "Required schema scope for structure collection "
            "(qualifies object identity within the Source)"
        ),
    }


_SERVICE_NAME_PROP: dict[str, Any] = {
    "type": "string",
    "minLength": 1,
    "maxLength": 256,
    "description": "Oracle service name / SID",
}
_OWNER_PROP: dict[str, Any] = {
    "type": "string",
    "minLength": 1,
    "maxLength": 256,
    "description": (
        "Required owner (schema) scope for structure collection "
        "(qualifies object identity within the Source)"
    ),
}


def _engine_schema(
    *,
    schema_id: str,
    title: str,
    default_port: int,
    ssl_modes: list[str],
    default_ssl_mode: str,
    include_cert_fields: bool,
    scope_properties: dict[str, dict[str, Any]],
    scope_required: list[str],
) -> dict[str, Any]:
    props = _base_properties(
        default_port=default_port,
        ssl_modes=ssl_modes,
        default_ssl_mode=default_ssl_mode,
        include_cert_fields=include_cert_fields,
    )
    props.update(deepcopy(scope_properties))
    required = ["host", "port", "username", "password", "ssl_mode", *scope_required]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        "title": title,
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": props,
    }


CONNECTOR_SPECS: dict[str, dict[str, Any]] = {
    "postgresql": _engine_schema(
        schema_id="postgresql.access.v1",
        title="PostgreSQL access",
        default_port=5432,
        ssl_modes=SSL_MODE_ENUM_POSTGRES,
        default_ssl_mode="require",
        include_cert_fields=True,
        scope_properties={
            "database": _DATABASE_PROP,
            "schema": _schema_prop(default="public"),
        },
        scope_required=["database", "schema"],
    ),
    "mssql": _engine_schema(
        schema_id="mssql.access.v1",
        title="Microsoft SQL Server access",
        default_port=1433,
        ssl_modes=SSL_MODE_ENUM_PLAIN,
        default_ssl_mode="disable",
        include_cert_fields=False,
        scope_properties={
            "database": _DATABASE_PROP,
            "schema": _schema_prop(default="dbo"),
        },
        scope_required=["database", "schema"],
    ),
    "oracle": _engine_schema(
        schema_id="oracle.access.v1",
        title="Oracle access",
        default_port=1521,
        ssl_modes=SSL_MODE_ENUM_PLAIN,
        default_ssl_mode="disable",
        include_cert_fields=False,
        scope_properties={
            "service_name": _SERVICE_NAME_PROP,
            "owner": _OWNER_PROP,
        },
        scope_required=["service_name", "owner"],
    ),
}

SUPPORTED_ENGINES = frozenset(CONNECTOR_SPECS.keys())


def get_connector_spec(engine: str) -> dict[str, Any]:
    spec = CONNECTOR_SPECS.get(engine)
    if spec is None:
        raise SourceEngineUnsupported()
    return deepcopy(spec)


def iter_secret_keys(schema: dict[str, Any]) -> set[str]:
    """Top-level property names marked x-secret (nested secrets not used yet)."""
    keys: set[str] = set()
    props = schema.get("properties") or {}
    for name, prop in props.items():
        if isinstance(prop, dict) and prop.get("x-secret") is True:
            keys.add(name)
    return keys


def project_access(engine: str, access: dict[str, Any]) -> dict[str, Any]:
    """Access with x-secret fields removed for read APIs."""
    spec = get_connector_spec(engine)
    secret_keys = iter_secret_keys(spec)
    return {k: v for k, v in access.items() if k not in secret_keys}
