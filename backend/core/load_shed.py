"""In-flight HTTP load shed → PLATFORM_CAPACITY_EXCEEDED (503 + Retry-After)."""

from __future__ import annotations

import threading

from starlette.types import ASGIApp, Receive, Scope, Send

from backend.core.errors import PlatformCapacityExceeded, problem_response
from backend.core.metrics import record_reject, set_http_inflight
from backend.core.runtime import get_runtime_capacity

_BYPASS_PATHS = frozenset({"/healthz", "/readyz", "/metrics"})


class LoadSheddingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._lock = threading.Lock()
        self._inflight = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        if path in _BYPASS_PATHS:
            await self.app(scope, receive, send)
            return
        cap = get_runtime_capacity()
        limit = cap.http_max_inflight
        admitted = False
        with self._lock:
            if self._inflight < limit:
                self._inflight += 1
                set_http_inflight(self._inflight, limit)
                admitted = True
        if not admitted:
            record_reject(PlatformCapacityExceeded.code)
            exc = PlatformCapacityExceeded()
            response = problem_response(
                status=exc.http_status,
                code=exc.code,
                detail=exc.message,
                headers=exc.extra_headers(),
            )
            await response(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        finally:
            with self._lock:
                self._inflight = max(0, self._inflight - 1)
                set_http_inflight(self._inflight, limit)
