"""Celery application factory for the platform async runtime."""

from __future__ import annotations

import os

from celery import Celery

from backend.core.celery_broker import celery_broker_url
from backend.core.config import get_settings
from backend.core.request_id import connect_celery_request_id, install_request_id_log_filter


def create_celery_app() -> Celery:
    settings = get_settings()
    app = Celery("refraq")
    app.conf.update(
        broker_url=celery_broker_url(settings),
        result_backend=None,
        task_ignore_result=True,
        task_track_started=False,
        worker_concurrency=settings.refraq_job_worker_concurrency,
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
celery_app.set_default()

install_request_id_log_filter()
connect_celery_request_id()

# Alias for `celery -A backend.worker.app`
app = celery_app
