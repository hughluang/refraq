"""OIDC authorization-code adapter: PKCE S256, discovery, token exchange, ID Token checks."""

from __future__ import annotations

import base64
import hashlib
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from backend.admin.federation.assertion import ExternalAssertion
from backend.admin.federation.errors import SsoAssertionRejected, SsoProviderUnavailable
from backend.admin.federation.protocols.oidc.claims import assertion_from_claims
from backend.admin.federation.protocols.oidc.discovery import OidcDiscovery, discover
from backend.admin.federation.protocols.oidc.jwks import ALLOWED_ALGS, signing_key
from backend.admin.federation.spec import ProviderRecord

TOKEN_TIMEOUT_SEC = 8.0


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorization_url(
    provider: ProviderRecord,
    *,
    redirect_uri: str,
    state: str,
    nonce: str,
    code_challenge: str,
) -> str:
    metadata = discover(provider)
    scopes = " ".join(dict.fromkeys(["openid", *provider.config.scopes]))
    return metadata.authorization_endpoint + "?" + urlencode(
        {
            "client_id": provider.config.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )


def _require_iss_match(
    metadata: OidcDiscovery, configured: str, response_iss: str | None
) -> None:
    if metadata.authorization_response_iss_parameter_supported and not response_iss:
        raise SsoAssertionRejected("Authorization response issuer is missing")
    if response_iss is not None and response_iss != configured:
        raise SsoAssertionRejected("Authorization response issuer does not match")


def _decode_id_token(
    token: str,
    *,
    jwks_uri: str,
    issuer: str,
    audience: str,
    nonce: str,
    allowed_algs: tuple[str, ...],
) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise SsoAssertionRejected() from exc
    alg = header.get("alg")
    if not isinstance(alg, str) or alg not in ALLOWED_ALGS or alg not in allowed_algs:
        raise SsoAssertionRejected("ID token algorithm is not allowed")
    kid = header.get("kid")
    if kid is not None and not isinstance(kid, str):
        raise SsoAssertionRejected("ID token kid is invalid")
    key = signing_key(jwks_uri, kid if isinstance(kid, str) else None, alg)
    try:
        claims = jwt.decode(
            token,
            key=key,
            algorithms=[alg],
            issuer=issuer,
            audience=audience,
            options={"require": ["iss", "sub", "aud", "exp", "iat"]},
            leeway=30,
        )
    except jwt.PyJWTError as exc:
        raise SsoAssertionRejected() from exc
    if claims.get("nonce") != nonce:
        raise SsoAssertionRejected("ID token nonce is invalid")
    aud = claims.get("aud")
    if isinstance(aud, list) and len(aud) > 1 and claims.get("azp") != audience:
        raise SsoAssertionRejected("ID token azp is invalid")
    azp = claims.get("azp")
    if isinstance(azp, str) and azp != audience:
        raise SsoAssertionRejected("ID token azp is invalid")
    return claims


def exchange(
    provider: ProviderRecord,
    *,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    nonce: str,
    response_iss: str | None,
) -> ExternalAssertion:
    metadata = discover(provider)
    _require_iss_match(metadata, provider.issuer, response_iss)
    try:
        response = httpx.post(
            metadata.token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": provider.config.client_id,
                "client_secret": provider.config.client_secret,
                "code_verifier": code_verifier,
            },
            timeout=TOKEN_TIMEOUT_SEC,
        )
    except httpx.HTTPError as exc:
        raise SsoProviderUnavailable() from exc
    if response.status_code >= 400:
        raise SsoAssertionRejected("OIDC code exchange failed")
    data = response.json()
    token = data.get("id_token") if isinstance(data, dict) else None
    if not isinstance(token, str):
        raise SsoAssertionRejected("ID token is missing")
    claims = _decode_id_token(
        token,
        jwks_uri=metadata.jwks_uri,
        issuer=provider.issuer,
        audience=provider.config.client_id,
        nonce=nonce,
        allowed_algs=metadata.id_token_signing_alg_values_supported,
    )
    return assertion_from_claims(provider, claims)
