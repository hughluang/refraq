"""Outbound Prometheus read. The browser never sees this address."""

from __future__ import annotations

import httpx

from backend.admin.host.errors import HostSeriesUnavailable


class PrometheusRead:
    def __init__(self, client: httpx.Client, base_url: str) -> None:
        self.client = client
        self.base = base_url.rstrip("/")

    def query_instant(self, query: str, *, time: int) -> dict:
        return self._get("/api/v1/query", {"query": query, "time": str(time)})

    def query_range(self, query: str, *, start: int, end: int, step: int) -> dict:
        return self._get(
            "/api/v1/query_range",
            {
                "query": query,
                "start": str(start),
                "end": str(end),
                "step": str(step),
            },
        )

    def _get(self, path: str, params: dict[str, str]) -> dict:
        try:
            response = self.client.get(f"{self.base}{path}", params=params)
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
