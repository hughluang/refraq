"""Celery application factory for the platform async runtime."""

from __future__ import annotations

import os
import sys

from celery import Celery

from celery.signals import (
    beat_init,
    celeryd_after_setup,
    celeryd_init,
    worker_process_init,
)

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
            "backend.entity.tasks",
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

# After set_default so @shared_task on entity.tasks binds to this app.
from backend.entity.tasks import init_worker_entity_pool  # noqa: E402

install_request_id_log_filter()
connect_celery_request_id()


def ensure_persistent_entity_pool_or_abort(**_kwargs: object) -> None:
    """Start gate: probe the entity pool after logging, or abort before ready.

    Probe failures raise Exception, which Celery Signal.send swallows. SystemExit
    is the process close path (same as core.entry) and is not swallowed.
    """
    try:
        init_worker_entity_pool()
    except Exception as exc:  # noqa: BLE001 — worker close path must exit
        print(f"entity pool open failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


celeryd_init.connect(init_parent_worker_runtime, weak=False)
beat_init.connect(init_parent_worker_runtime, weak=False)
celeryd_after_setup.connect(ensure_persistent_entity_pool_or_abort, weak=False)
worker_process_init.connect(mark_worker_process, weak=False)

# Occupancy renew / startup local reap (Job primitive; shares Beat with schedules).
import backend.worker.occupancy  # noqa: E402,F401

# Alias for `celery -A backend.worker.app`
app = celery_app
