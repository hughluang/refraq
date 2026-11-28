"""Single external HTTP seam for OIDC discovery, JWKS, code exchange, and client jwks_uri."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

import httpx

from backend.admin.federation.errors import SsoAssertionRejected, SsoProviderUnavailable

OIDC_HTTP_TIMEOUT_SEC = 8.0


class OidcHttpPort(Protocol):
    def get_json(self, url: str) -> dict[str, Any]: ...

    def post_form(self, url: str, data: Mapping[str, str]) -> dict[str, Any]: ...


class HttpxOidcAdapter:
    """Production adapter using httpx with bounded timeouts."""

    def __init__(self, *, timeout_sec: float = OIDC_HTTP_TIMEOUT_SEC) -> None:
        self._timeout = timeout_sec

    def get_json(self, url: str) -> dict[str, Any]:
        try:
            response = httpx.get(url, timeout=self._timeout)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SsoProviderUnavailable() from exc
        data = response.json()
        if not isinstance(data, dict):
            raise SsoAssertionRejected("Remote JSON document is invalid")
        return data

    def post_form(self, url: str, data: Mapping[str, str]) -> dict[str, Any]:
        try:
            response = httpx.post(url, data=dict(data), timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise SsoProviderUnavailable() from exc
        if response.status_code >= 400:
            raise SsoAssertionRejected("OIDC token endpoint rejected request")
        payload = response.json()
        if not isinstance(payload, dict):
            raise SsoAssertionRejected("OIDC token response is invalid")
        return payload


_DEFAULT_HTTP: OidcHttpPort = HttpxOidcAdapter()


def get_default_oidc_http() -> OidcHttpPort:
    return _DEFAULT_HTTP
