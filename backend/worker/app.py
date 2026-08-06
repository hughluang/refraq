"""Celery application factory for the platform async runtime."""

from __future__ import annotations

import os

from celery import Celery

from backend.core.config import get_settings


def _broker_url() -> str:
    settings = get_settings()
    if settings.celery_broker_url:
        return settings.celery_broker_url
    if settings.redis_url:
        # Prefer a separate logical DB when only REDIS_URL is set.
        base = settings.redis_url.rsplit("/", 1)[0]
        return f"{base}/2"
    return "redis://127.0.0.1:6379/2"


def create_celery_app() -> Celery:
    app = Celery("refraq")
    app.conf.update(
        broker_url=_broker_url(),
        result_backend=None,
        task_ignore_result=True,
        task_track_started=False,
        worker_concurrency=get_settings().refraq_ingestion_worker_concurrency,
        imports=(
            "backend.metadata.tasks",
            "backend.worker.tasks",
        ),
        beat_scheduler="backend.worker.scheduler:DatabaseScheduler",
        timezone="UTC",
        enable_utc=True,
    )
    if os.environ.get("CELERY_TASK_ALWAYS_EAGER") == "1":
        app.conf.task_always_eager = True
        app.conf.task_eager_propagates = True
    return app


celery_app = create_celery_app()

# Alias for `celery -A backend.worker.app`
app = celery_app
