"""Celery application factory for the platform async runtime."""

from __future__ import annotations

import os

from celery import Celery

from celery.signals import beat_init, celeryd_init, worker_process_init

from backend.core.celery_broker import celery_broker_url
from backend.core.config import get_settings
from backend.core.request_id import connect_celery_request_id, install_request_id_log_filter
from backend.core.worker_runtime import init_parent_worker_runtime, mark_worker_process
from backend.worker.api import ensure_system_schedules
from backend.worker.parameters import BEAT_MAX_INTERVAL_SEC, assemble_system_parameters

assemble_system_parameters()
ensure_system_schedules()


def create_celery_app() -> Celery:
    settings = get_settings()
    app = Celery("refraq")
    app.conf.update(
        broker_url=celery_broker_url(settings),
        result_backend=None,
        task_ignore_result=True,
        task_track_started=False,
        imports=(
            "backend.metadata.tasks",
            "backend.metadata.source_jobs",
            "backend.worker.tasks",
        ),
        beat_scheduler="backend.worker.scheduler:DatabaseScheduler",
        beat_max_loop_interval=BEAT_MAX_INTERVAL_SEC,
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


celeryd_init.connect(init_parent_worker_runtime, weak=False)
beat_init.connect(init_parent_worker_runtime, weak=False)
worker_process_init.connect(mark_worker_process, weak=False)

# Occupancy renew / startup local reap (Job primitive; shares Beat with schedules).
import backend.worker.occupancy  # noqa: E402,F401

# Alias for `celery -A backend.worker.app`
app = celery_app
