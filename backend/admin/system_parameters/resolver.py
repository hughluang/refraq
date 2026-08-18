"""Resolve, occupy, write, and last-known-good for System Parameters."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime

from backend.admin.system_parameters.errors import ParameterReadFailed, ParameterValueInvalid
from backend.admin.system_parameters.registry import get_parameter_spec, list_registered_specs
from backend.admin.system_parameters.spec import ParameterSource, ParameterSpec, ParameterValue
from backend.admin.system_parameters.store import (
    ParameterRecord,
    get_parameter_store,
    new_seed_record,
)
from backend.core.time import utc_now

logger = logging.getLogger(__name__)

_last_known: dict[str, ResolvedParameter] = {}
_last_known_lock = threading.Lock()


@dataclass(frozen=True, slots=True)
class ResolvedParameter:
    key: str
    value: ParameterValue
    previous_value: ParameterValue
    source: ParameterSource
    updated_at: datetime | None
    updated_by_user_id: str | None


@dataclass(frozen=True, slots=True)
class ResolvedIntParameter:
    key: str
    value: int
    previous_value: int | None
    source: ParameterSource
    updated_at: datetime | None
    updated_by_user_id: str | None


def occupy_registered_parameters() -> None:
    """Insert a seed row when the key is missing. Never overwrite an existing row."""
    store = get_parameter_store()
    for spec in list_registered_specs():
        store.occupy_if_missing(new_seed_record(spec.key, spec.seed))


def read_stored_parameter(key: str) -> ResolvedParameter:
    """Return the stored value untouched. Store failure / unreadable row raises."""
    spec = get_parameter_spec(key)
    try:
        record = get_parameter_store().get(key)
    except Exception as exc:
        logger.exception("system parameter read failed key=%s", key)
        raise ParameterReadFailed(f"system parameter store read failed: {key}") from exc
    if record is None:
        resolved = _from_seed(spec)
        _remember(resolved)
        return resolved
    if not _record_is_readable(record):
        logger.warning(
            "system parameter %s stored row is unreadable source=%r",
            key,
            record.source,
        )
        raise ParameterReadFailed(
            f"system parameter stored row is unreadable: {key}"
        )
    resolved = _from_record(record)
    _remember(resolved)
    return resolved


def resolve_int(key: str) -> ResolvedIntParameter:
    """Admit the stored value against the integer constraint; otherwise fall back.

    Store failure and unreadable rows use last-known-good, then seed — never raise.
    """
    spec = get_parameter_spec(key)
    raw = _read_for_consumer(spec)
    value = _as_int(spec.constraint.fallback(raw.value, spec.seed), spec)
    previous: int | None = None
    if raw.previous_value is not None:
        previous = _as_int(spec.constraint.fallback(raw.previous_value, spec.seed), spec)
    return ResolvedIntParameter(
        key=spec.key,
        value=value,
        previous_value=previous,
        source=raw.source,
        updated_at=raw.updated_at,
        updated_by_user_id=raw.updated_by_user_id,
    )


def validate_parameter_write(key: str, value: object) -> ParameterValue:
    """Admit a write: registered key and declared constraint. Does not persist."""
    spec = get_parameter_spec(key)
    if not spec.constraint.admit(value):
        raise ParameterValueInvalid(f"{spec.key} does not satisfy the declared constraint")
    return value  # type: ignore[return-value]


def set_parameter(
    key: str,
    value: object,
    *,
    actor_user_id: str | None,
) -> ResolvedParameter:
    spec = get_parameter_spec(key)
    admitted = validate_parameter_write(key, value)
    store = get_parameter_store()
    existing = store.get(key)
    previous = existing.value if existing is not None else None
    record = ParameterRecord(
        key=key,
        value=admitted,
        previous_value=previous,
        source="user",
        updated_at=utc_now(),
        updated_by_user_id=actor_user_id,
    )
    store.upsert(record)
    resolved = _from_record(record)
    _remember(resolved)
    return resolved


def reset_parameter(key: str, *, actor_user_id: str | None) -> ResolvedParameter:
    spec = get_parameter_spec(key)
    store = get_parameter_store()
    existing = store.get(key)
    previous = existing.value if existing is not None else None
    record = ParameterRecord(
        key=key,
        value=spec.seed,
        previous_value=previous,
        source="seed",
        updated_at=utc_now(),
        updated_by_user_id=actor_user_id,
    )
    store.upsert(record)
    resolved = _from_record(record)
    _remember(resolved)
    return resolved


def clear_last_known() -> None:
    with _last_known_lock:
        _last_known.clear()


def _read_for_consumer(spec: ParameterSpec) -> ResolvedParameter:
    """Consumer path: last-known-good, then seed, when the strict catalog read fails."""
    try:
        return read_stored_parameter(spec.key)
    except ParameterReadFailed:
        return _degraded(spec.key, spec)


def _is_json_scalar(value: object) -> bool:
    return value is None or isinstance(value, (int, float, str, bool))


def _record_is_readable(record: ParameterRecord) -> bool:
    if record.source not in {"seed", "user"}:
        return False
    if not _is_json_scalar(record.value):
        return False
    if record.previous_value is not None and not _is_json_scalar(record.previous_value):
        return False
    return True


def _as_int(value: ParameterValue, spec: ParameterSpec) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ParameterValueInvalid(f"{spec.key} did not resolve to an integer")
    return value


def _from_record(record: ParameterRecord) -> ResolvedParameter:
    source: ParameterSource = record.source  # type: ignore[assignment]
    return ResolvedParameter(
        key=record.key,
        value=record.value,
        previous_value=record.previous_value,
        source=source,
        updated_at=record.updated_at,
        updated_by_user_id=record.updated_by_user_id,
    )


def _from_seed(spec: ParameterSpec) -> ResolvedParameter:
    return ResolvedParameter(
        key=spec.key,
        value=spec.seed,
        previous_value=None,
        source="seed",
        updated_at=None,
        updated_by_user_id=None,
    )


def _degraded(key: str, spec: ParameterSpec) -> ResolvedParameter:
    cached = _cached(key)
    if cached is not None:
        return cached
    return _from_seed(spec)


def _remember(resolved: ResolvedParameter) -> None:
    with _last_known_lock:
        _last_known[resolved.key] = resolved


def _cached(key: str) -> ResolvedParameter | None:
    with _last_known_lock:
        return _last_known.get(key)
