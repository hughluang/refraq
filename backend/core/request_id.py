"""Request ID (X-Request-ID) middleware, log context, and Celery header transfer."""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

from celery.signals import before_task_publish, task_postrun, task_prerun
from starlette.types import ASGIApp, Receive, Scope, Send

HEADER_NAME = "X-Request-ID"
HEADER_NAME_BYTES = b"x-request-id"
CELERY_HEADER = "request_id"
SCOPE_KEY = "refraq_request_id"

correlation_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def is_valid_request_id(value: str) -> bool:
    """Accept UUID (with or without dashes) and nginx 32-hex `$request_id`."""
    if not value or len(value) > 36:
        return False
    compact = value.replace("-", "")
    if len(compact) != 32:
        return False
    try:
        int(compact, 16)
    except ValueError:
        return False
    return True


def get_request_id() -> str | None:
    return correlation_id.get()


class RequestIdLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        inbound = ""
        for key, value in scope.get("headers", []):
            if key == HEADER_NAME_BYTES:
                inbound = value.decode("latin-1")
                break
        rid = inbound if inbound and is_valid_request_id(inbound) else uuid4().hex
        scope[SCOPE_KEY] = rid
        token = correlation_id.set(rid)

        async def send_with_id(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                raw = [
                    (key, value)
                    for key, value in (message.get("headers") or [])
                    if key.lower() != HEADER_NAME_BYTES
                ]
                raw.append((HEADER_NAME_BYTES, rid.encode("latin-1")))
                message = {**message, "headers": raw}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            correlation_id.reset(token)


def install_request_id_log_filter() -> None:
    root = logging.getLogger()
    if not any(isinstance(item, RequestIdLogFilter) for item in root.filters):
        root.addFilter(RequestIdLogFilter())
    for handler in root.handlers:
        if not any(isinstance(item, RequestIdLogFilter) for item in handler.filters):
            handler.addFilter(RequestIdLogFilter())


def transfer_request_id_to_celery(headers: dict[str, str], **kwargs: object) -> None:
    rid = get_request_id()
    if rid:
        headers[CELERY_HEADER] = rid


def load_request_id_from_celery(task: object, **kwargs: object) -> None:
    request = getattr(task, "request", None)
    getter = getattr(request, "get", None) if request is not None else None
    id_value = getter(CELERY_HEADER) if callable(getter) else None
    if id_value:
        correlation_id.set(str(id_value))
    else:
        correlation_id.set(uuid4().hex)


def clear_request_id(**kwargs: object) -> None:
    correlation_id.set(None)


def connect_celery_request_id() -> None:
    before_task_publish.connect(transfer_request_id_to_celery, weak=False)
    task_prerun.connect(load_request_id_from_celery, weak=False)
    task_postrun.connect(clear_request_id, weak=False)
