"""Worker main-process occupancy renewal and startup leftover abandon.

Occupancy is a Job primitive; it ships with schedules only because they share Beat.
"""

from __future__ import annotations

import logging
import threading

from celery.signals import worker_ready, worker_shutdown

from backend.jobs.parameters import job_lost_detection_sec
from backend.jobs.store import (
    UNKNOWN_WORKER_ID,
    fail_leftover_occupancy,
    occupancy_worker_id,
    touch_occupancy,
)

logger = logging.getLogger(__name__)

_worker_id: str | None = None
_abandoned_for: str | None = None
_timer: threading.Timer | None = None
_stop = threading.Event()


def _renew_loop() -> None:
    global _timer
    if _stop.is_set() or _worker_id is None:
        return
    try:
        touch_occupancy(_worker_id)
    except Exception:  # noqa: BLE001
        logger.exception("occupancy renew failed worker=%s", _worker_id)
    lost = job_lost_detection_sec()
    interval = max(5.0, float(lost) / 3.0)
    _timer = threading.Timer(interval, _renew_loop)
    _timer.daemon = True
    _timer.start()


@worker_ready.connect
def on_worker_ready(sender=None, **_kwargs) -> None:
    global _worker_id, _abandoned_for
    _stop.clear()
    hostname = getattr(sender, "hostname", None) if sender is not None else None
    _worker_id = occupancy_worker_id(hostname)
    # Unknown is a shared slot — abandoning it would be a global reap.
    # Same id already abandoned this process generation: do not kill this gen's claims.
    if _worker_id != UNKNOWN_WORKER_ID and _abandoned_for != _worker_id:
        abandoned = fail_leftover_occupancy(_worker_id)
        _abandoned_for = _worker_id
        if abandoned:
            logger.info(
                "startup leftover occupancy abandon worker=%s count=%s",
                _worker_id,
                abandoned,
            )
    _renew_loop()


@worker_shutdown.connect
def on_worker_shutdown(**_kwargs) -> None:
    global _timer, _worker_id, _abandoned_for
    _stop.set()
    if _timer is not None:
        _timer.cancel()
        _timer = None
    _worker_id = None
    _abandoned_for = None
