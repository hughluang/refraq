"""Transactional, typed, redacted notification intent for product callers."""

import hashlib
import json
import math
import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.admin.notifications.errors import NotificationRouteInvalid
from backend.admin.notifications.models import NotificationEventRow
from backend.core.time import parse_instant, utc_now

__all__ = ["enqueue_notification"]

_EVENT_TYPES = frozenset({
    "cdc.prerequisite_blocked", "cdc.source_pressure", "cdc.buffer_blocked",
    "cdc.read_unavailable", "cdc.disable_unconfirmed", "cdc.history_gap",
    "cdc.recovery_blocked", "cdc.generation_published",
})
_SCOPE_KEYS = frozenset({"source_id", "mirror_id", "profile_id"})
_COUNTERS = frozenset({"owner_epoch", "control_revision", "capture_generation"})
_SAFE_VALUES = frozenset({"pass", "fail", "unknown", "not_applicable", "pending", "blocked",
    "available", "unavailable", "published", "retained", "lost", "confirmed", "unconfirmed"})
_ACTIONS = frozenset({"inspect_prerequisites", "inspect_source_pressure", "inspect_buffer",
    "restore_target", "confirm_stop", "authorize_recovery", "inspect_recovery", "observe_publication"})


def _identifier(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:@+-]{1,128}", value) is not None


def enqueue_notification(session: Session, *, event_id: str, event_type: str, scope: dict,
                         evidence: dict, severity: str, responder: str, safe_action: str) -> str:
    """Join the caller's management transaction; event_id denotes a material fault transition."""
    if (not _identifier(event_id) or len(event_id) > 64 or event_type not in _EVENT_TYPES
            or severity not in {"info", "warning", "critical"}
            or not _identifier(responder) or safe_action not in _ACTIONS
            or not isinstance(scope, dict) or not scope or set(scope) - _SCOPE_KEYS
            or any(not _identifier(value) for value in scope.values())
            or not isinstance(evidence, dict)
            or set(evidence) - (_COUNTERS | {"history_epoch", "observed_at", "expected", "observed", "state"})):
        raise NotificationRouteInvalid()
    for key, value in evidence.items():
        if key in _COUNTERS:
            valid = type(value) is int and value >= 0
        elif key == "history_epoch":
            valid = isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value) is not None
        elif key == "observed_at":
            try:
                parse_instant(value)
                valid = True
            except (ValueError, TypeError, AttributeError):
                valid = False
        elif key == "state":
            valid = isinstance(value, str) and value in _SAFE_VALUES
        else:
            valid = ((type(value) in {int, float} and math.isfinite(value))
                     or value is None or (isinstance(value, str) and value in _SAFE_VALUES))
        if not valid:
            raise NotificationRouteInvalid()
    payload = dict(event_id=event_id, event_type=event_type, scope=dict(scope), evidence=dict(evidence),
                   severity=severity, responder=responder, safe_action=safe_action)
    key = hashlib.sha256(json.dumps([event_type, scope, event_id], sort_keys=True).encode()).hexdigest()
    existing = session.scalar(select(NotificationEventRow).where(NotificationEventRow.dedup_key == key))
    if existing is not None:
        return existing.id
    try:
        with session.begin_nested():
            session.add(NotificationEventRow(id=event_id, dedup_key=key, payload=payload,
                channel_revision=None, kind="event", route="primary", state="pending", attempts=0,
                next_attempt_at=utc_now(), outcomes={}))
            session.flush()
    except IntegrityError:
        existing = session.scalar(select(NotificationEventRow).where(NotificationEventRow.dedup_key == key))
        if existing is None:
            raise NotificationRouteInvalid() from None
        return existing.id
    return event_id
