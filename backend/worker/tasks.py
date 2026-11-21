"""Platform Celery tasks (system schedules)."""

from __future__ import annotations

import logging

from celery import shared_task

from backend.admin.notifications.configuration import EgressPolicy
from backend.admin.notifications.delivery import DeliveryBudget, deliver_due
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.time import utc_now

from backend.channel.tasks import seal_dataset_expiry
from backend.entity.tasks import (
    ACCESS_LOG_SCHEDULE_KEY,
    CHANGE_LOG_SCHEDULE_KEY,
    CHANGE_LOG_TASK_NAME,
    purge_expired_access_logs,
    purge_expired_change_logs,
)
from backend.jobs.store import get_job_store, reap_stuck_running_jobs
from backend.worker.due import consume_due_tick
from backend.worker.models import REAPER_SCHEDULE_KEY
from backend.worker.parameters import NOTIFICATION_SCHEDULE_KEY, NOTIFICATION_TASK_NAME
from backend.worker.schedules import get_schedule_store

logger = logging.getLogger(__name__)


@shared_task(name=NOTIFICATION_TASK_NAME)
def deliver_notifications() -> dict[str, str | int]:
    settings = get_settings()
    approved = settings.notification_delivery
    if approved is None or not settings.notification_reviewed_origins:
        logger.warning("notification delivery blocked: reviewed policy and explicit budget required")
        return {"status": "blocked", "code": "NOTIFICATION_DEPLOYMENT_UNCONFIGURED"}
    policy = EgressPolicy(settings.notification_reviewed_origins)
    budget = DeliveryBudget(
        max_attempts_per_route=approved.max_attempts_per_route,
        retry_delays_seconds=approved.retry_delays_seconds,
        timeout_seconds=approved.timeout_seconds,
        batch_size=approved.batch_size,
    )
    record = get_schedule_store().get_by_key(NOTIFICATION_SCHEDULE_KEY)
    if record is None:
        return {"status": "blocked", "code": "NOTIFICATION_DUTY_UNCONFIGURED"}
    with session_scope() as session:
        consumed = consume_due_tick(record.id, session=session)
        if consumed["status"] != "system":
            return {"status": consumed["status"]}
        count = deliver_due(session, policy=policy, budget=budget, now=utc_now())
    return {"status": "processed", "processed": count}


@shared_task(name="backend.worker.tasks.reap_stuck_jobs")
def reap_stuck_jobs() -> dict[str, int]:
    record = get_schedule_store().get_by_key(REAPER_SCHEDULE_KEY)
    if record is not None:
        consume_due_tick(record.id)
    running_ids = [item.id for item in get_job_store().list(status="running")[0]]
    count = reap_stuck_running_jobs()
    for job_id in running_ids:
        seal_dataset_expiry(job_id)
    return {"reaped": count}


@shared_task(name="backend.worker.tasks.purge_access_logs")
def purge_access_logs() -> dict[str, int]:
    record = get_schedule_store().get_by_key(ACCESS_LOG_SCHEDULE_KEY)
    if record is not None:
        consume_due_tick(record.id)
    return {"deleted": purge_expired_access_logs()}


@shared_task(name=CHANGE_LOG_TASK_NAME)
def purge_change_logs() -> dict[str, int]:
    record = get_schedule_store().get_by_key(CHANGE_LOG_SCHEDULE_KEY)
    if record is not None:
        consume_due_tick(record.id)
    return {"deleted": purge_expired_change_logs()}
