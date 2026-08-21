"""Canonical browser Host used for Console origin (OIDC callback URI)."""

from __future__ import annotations

import re

# Hostname or [IPv6], optional :port. No scheme, userinfo, path, or query.
_HOST_RE = re.compile(
    r"^(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?"
    r"|\[[0-9A-Fa-f:]+\])(?::\d{1,5})?$"
)
_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1"})


def valid_browser_host(value: str) -> bool:
    if not value or len(value) > 262:
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return False
    return _HOST_RE.fullmatch(value) is not None


def hostname_of(host: str) -> str:
    if host.startswith("["):
        end = host.find("]")
        if end == -1:
            return ""
        return host[1:end]
    if host.count(":") == 1:
        return host.rsplit(":", 1)[0]
    return host


def is_loopback_host(host: str) -> bool:
    return hostname_of(host).lower() in _LOOPBACK


def canonical_browser_host(
    *,
    configured: str | None,
    forwarded_host: str | None,
    request_host: str | None,
) -> str | None:
    """Trusted Host for the browser-facing Console origin.

    A configured value wins. Otherwise only a syntactically valid loopback
    Host is accepted so a client-supplied Host cannot become an OIDC
    ``redirect_uri``.
    """
    chosen: str | None = None
    if configured:
        cleaned = configured.strip()
        chosen = cleaned if valid_browser_host(cleaned) else None
    else:
        raw = ""
        if forwarded_host:
            raw = forwarded_host.split(",")[0].strip()
        elif request_host:
            raw = request_host.strip()
        if valid_browser_host(raw) and is_loopback_host(raw):
            chosen = raw
    return chosen
