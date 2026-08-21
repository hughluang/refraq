"""OpenID Connect Discovery 1.0 — issuer in the document must equal the configured issuer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from backend.admin.federation.errors import SsoAssertionRejected, SsoProviderUnavailable
from backend.admin.federation.protocols.oidc.jwks import permitted_signing_algs
from backend.admin.federation.spec import ProviderRecord

DISCOVERY_TIMEOUT_SEC = 8.0


@dataclass(frozen=True)
class OidcDiscovery:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    authorization_response_iss_parameter_supported: bool
    id_token_signing_alg_values_supported: tuple[str, ...]


def _get_json(url: str) -> dict[str, Any]:
    try:
        response = httpx.get(url, timeout=DISCOVERY_TIMEOUT_SEC)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SsoProviderUnavailable() from exc
    data = response.json()
    if not isinstance(data, dict):
        raise SsoAssertionRejected("OIDC metadata is invalid")
    return data


def discovery_url(issuer: str) -> str:
    return issuer.rstrip("/") + "/.well-known/openid-configuration"


def _signing_algs(data: dict[str, Any]) -> tuple[str, ...]:
    raw = data.get("id_token_signing_alg_values_supported")
    if raw is None:
        return ("RS256",)
    if (
        not isinstance(raw, list)
        or not raw
        or any(not isinstance(item, str) or not item for item in raw)
    ):
        raise SsoAssertionRejected("OIDC ID token signing algorithms are invalid")
    return tuple(str(item) for item in raw)


def discover(provider: ProviderRecord) -> OidcDiscovery:
    data = _get_json(discovery_url(provider.issuer))
    issuer = data.get("issuer")
    if not isinstance(issuer, str) or issuer != provider.issuer:
        raise SsoAssertionRejected("OIDC discovery issuer does not match")
    authorization_endpoint = data.get("authorization_endpoint")
    token_endpoint = data.get("token_endpoint")
    jwks_uri = data.get("jwks_uri")
    if not all(
        isinstance(value, str) and value
        for value in (authorization_endpoint, token_endpoint, jwks_uri)
    ):
        raise SsoAssertionRejected("OIDC metadata is incomplete")
    return OidcDiscovery(
        issuer=issuer,
        authorization_endpoint=str(authorization_endpoint),
        token_endpoint=str(token_endpoint),
        jwks_uri=str(jwks_uri),
        authorization_response_iss_parameter_supported=bool(
            data.get("authorization_response_iss_parameter_supported", False)
        ),
        id_token_signing_alg_values_supported=permitted_signing_algs(_signing_algs(data)),
    )
