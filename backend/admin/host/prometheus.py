"""Outbound Prometheus read. The browser never sees this address."""

from __future__ import annotations

import httpx

from backend.admin.host.errors import HostSeriesUnavailable
from backend.core.config import get_settings


def query_instant(query: str, *, time: int) -> dict:
    return _get("/api/v1/query", {"query": query, "time": str(time)})


def query_range(query: str, *, start: int, end: int, step: int) -> dict:
    return _get(
        "/api/v1/query_range",
        {
            "query": query,
            "start": str(start),
            "end": str(end),
            "step": str(step),
        },
    )


def _get(path: str, params: dict[str, str]) -> dict:
    base = get_settings().refraq_prometheus_url.rstrip("/")
    try:
        response = httpx.get(f"{base}{path}", params=params, timeout=5.0)
    except httpx.HTTPError as exc:
        raise HostSeriesUnavailable() from exc
    if response.status_code != 200:
        raise HostSeriesUnavailable()
    try:
        body = response.json()
    except ValueError as exc:
        raise HostSeriesUnavailable() from exc
    if not isinstance(body, dict) or body.get("status") != "success":
        raise HostSeriesUnavailable()
    return body
