"""Shared Celery broker URL resolution (no worker package dependency)."""

from __future__ import annotations

from backend.core.config import Settings


def celery_broker_url(settings: Settings) -> str:
    """Resolve Celery broker URL from explicit settings.

    Prefers ``CELERY_BROKER_URL``, else derives a sibling logical DB from
    ``REDIS_URL``. Raises if neither is configured — callers must not guess
    a localhost broker.
    """
    if settings.celery_broker_url:
        return settings.celery_broker_url
    if settings.redis_url:
        base = settings.redis_url.rsplit("/", 1)[0]
        return f"{base}/2"
    raise ValueError(
        "Celery broker requires CELERY_BROKER_URL or REDIS_URL; "
        "refusing to invent a default"
    )
