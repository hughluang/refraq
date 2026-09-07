"""Admit work that waits on an external system (ADR 0045)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TypeVar

from backend.core.bulkhead import (
    ActorShareExceeded,
    CapacityExceeded,
    get_peek_bulkhead,
)
from backend.core.errors import AdmissionActorLimitExceeded, AdmissionCapacityExceeded
from backend.core.metrics import record_reject
from backend.core.request_id import get_request_id

__all__ = [
    "GUEST_ACTOR",
    "await_admitted",
]

logger = logging.getLogger(__name__)

GUEST_ACTOR = "guest"

T = TypeVar("T")


def _reject_capacity(exc: CapacityExceeded, actor_key: str) -> AdmissionCapacityExceeded:
    record_reject(AdmissionCapacityExceeded.code)
    logger.warning(
        "admission reject code=%s actor=%s occupied=%s limit=%s request_id=%s",
        AdmissionCapacityExceeded.code,
        actor_key,
        exc.occupied,
        exc.limit,
        get_request_id() or "-",
    )
    return AdmissionCapacityExceeded()


def _reject_share(exc: ActorShareExceeded, actor_key: str) -> AdmissionActorLimitExceeded:
    record_reject(AdmissionActorLimitExceeded.code)
    logger.warning(
        "admission reject code=%s actor=%s occupied=%s limit=%s request_id=%s",
        AdmissionActorLimitExceeded.code,
        actor_key,
        exc.occupied,
        exc.limit,
        get_request_id() or "-",
    )
    return AdmissionActorLimitExceeded()


async def await_admitted(actor_key: str, fn: Callable[[], T]) -> T:
    """Run `fn` in the admission pool. No queue: full pool / share fails immediately."""

    try:
        future = get_peek_bulkhead().submit_nowait(actor_key, fn)
    except ActorShareExceeded as exc:
        raise _reject_share(exc, actor_key) from exc
    except CapacityExceeded as exc:
        raise _reject_capacity(exc, actor_key) from exc
    return await asyncio.wrap_future(future)
