"""Protocol spec, provider config, and store records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

ProtocolName = Literal["oidc"]
AdmissionReason = Literal[
    "auto_disabled",
    "group_missing",
    "group_overflow",
    "group_not_allowed",
    "account_collision",
]

SUPPORTED_PROTOCOLS: frozenset[str] = frozenset({"oidc"})
DEFAULT_SCOPES: tuple[str, ...] = ("openid", "profile", "email")
SUBJECT_MAX_LEN = 255
ACCOUNT_MAX_LEN = 64

OIDC_PROTOCOL_SPEC: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "refraq://identity-providers/oidc",
    "title": "OIDC Identity Provider",
    "type": "object",
    "additionalProperties": False,
    "required": ["issuer", "client_id"],
    "properties": {
        "issuer": {
            "type": "string",
            "minLength": 1,
            "maxLength": 512,
            "description": "OpenID Provider issuer, no trailing slash",
        },
        "client_id": {"type": "string", "minLength": 1, "maxLength": 256},
        "client_secret": {
            "type": "string",
            "minLength": 1,
            "maxLength": 4096,
            "x-secret": True,
        },
        "scopes": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 64},
            "default": list(DEFAULT_SCOPES),
        },
        "auto_provision": {"type": "boolean", "default": False},
        "group_claim": {"type": "string", "minLength": 1, "maxLength": 128, "default": "groups"},
        "group_allowlist": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 256},
            "default": [],
        },
        "default_role_id": {"type": "string", "minLength": 1, "maxLength": 64},
    },
}


@dataclass
class OidcConfig:
    issuer: str
    client_id: str
    client_secret: str
    scopes: list[str] = field(default_factory=lambda: list(DEFAULT_SCOPES))
    auto_provision: bool = False
    group_claim: str = "groups"
    group_allowlist: list[str] = field(default_factory=list)
    default_role_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "issuer": self.issuer,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scopes": list(self.scopes),
            "auto_provision": self.auto_provision,
            "group_claim": self.group_claim,
            "group_allowlist": list(self.group_allowlist),
            "default_role_id": self.default_role_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OidcConfig":
        scopes = data.get("scopes") or list(DEFAULT_SCOPES)
        allowlist = data.get("group_allowlist") or []
        return cls(
            issuer=str(data["issuer"]),
            client_id=str(data["client_id"]),
            client_secret=str(data.get("client_secret") or ""),
            scopes=[str(item) for item in scopes],
            auto_provision=bool(data.get("auto_provision", False)),
            group_claim=str(data.get("group_claim") or "groups"),
            group_allowlist=[str(item) for item in allowlist],
            default_role_id=(
                str(data["default_role_id"]) if data.get("default_role_id") else None
            ),
        )


@dataclass
class ProviderRecord:
    id: str
    protocol: ProtocolName
    display_name: str
    issuer: str
    enabled: bool
    config: OidcConfig
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class BindingRecord:
    id: str
    issuer: str
    subject: str
    user_id: str
    provider_id: str | None = None
    email: str | None = None
    display_name: str | None = None
    linked_at: datetime | None = None
    last_login_at: datetime | None = None


@dataclass
class PendingRecord:
    id: str
    issuer: str
    subject: str
    account_hint: str
    admission_reason: str
    attempt_count: int
    first_seen_at: datetime
    last_attempt_at: datetime
    expires_at: datetime
    provider_id: str | None = None
    email: str | None = None
    display_name: str | None = None
    groups: tuple[str, ...] = ()
    claims: dict[str, object] = field(default_factory=dict)
