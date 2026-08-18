"""System Parameter mechanism tests (occupy, resolve, grace, write-through)."""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic.fields import FieldInfo

from backend.admin.parameters import ADMIN_PARAMETER_SPECS
from backend.admin.system_parameters import (
    JSON_SCHEMA_PROFILE_KEYWORDS,
    IntConstraint,
    ParameterReadFailed,
    ParameterRecord,
    ParameterSpec,
    UnregisteredParameter,
    clear_last_known,
    get_parameter_spec,
    get_parameter_store,
    list_registered_specs,
    occupy_registered_parameters,
    read_stored_parameter,
    register_parameters,
    reset_parameter,
    reset_parameter_registry,
    reset_system_parameters,
    resolve_int,
    set_parameter,
)
from backend.admin.system_parameters.store import MemoryParameterStore
from backend.core.config import Settings
from backend.core.time import FixedClock, parse_instant, reset_clock, set_clock, utc_now
from backend.jobs.parameters import JOBS_PARAMETER_SPECS, reaper_lost_detection_sec
from backend.jobs.store import (
    ERROR_WORKER_LOST,
    claim_queued,
    create_queued_job,
    get_job_store,
    reap_stale_occupancy,
)
from backend.worker.api import ensure_system_schedules
from backend.worker.models import REAPER_SCHEDULE_KEY
from backend.worker.parameters import assemble_system_parameters
from backend.worker.schedules import get_schedule_store

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_occupy_is_insert_if_missing() -> None:
    assemble_system_parameters()
    set_parameter("admin_session_ttl_hours", 12, actor_user_id=None)
    occupy_registered_parameters()
    resolved = resolve_int("admin_session_ttl_hours")
    assert resolved.value == 12
    assert resolved.source == "user"


def test_reset_restores_seed_source() -> None:
    assemble_system_parameters()
    set_parameter("admin_session_ttl_hours", 8, actor_user_id="user_1")
    assert resolve_int("admin_session_ttl_hours").source == "user"
    reset_parameter("admin_session_ttl_hours", actor_user_id="user_1")
    resolved = resolve_int("admin_session_ttl_hours")
    assert resolved.value == 8
    assert resolved.source == "seed"


def test_persist_visible_after_fresh_resolver() -> None:
    assemble_system_parameters()
    set_parameter("job_lost_detection_sec", 90, actor_user_id=None)
    clear_last_known()
    assert resolve_int("job_lost_detection_sec").value == 90


def test_memory_store_is_process_local() -> None:
    assemble_system_parameters()
    set_parameter("admin_session_ttl_hours", 12, actor_user_id=None)
    assert get_parameter_store().get("admin_session_ttl_hours") is not None
    other = MemoryParameterStore()
    assert other.get("admin_session_ttl_hours") is None


def test_unregistered_key_raises() -> None:
    assemble_system_parameters()
    with pytest.raises(UnregisteredParameter):
        resolve_int("not_a_registered_key")


def test_catalog_serves_raw_stored_value() -> None:
    assemble_system_parameters()
    store = get_parameter_store()
    store.upsert(
        ParameterRecord(
            key="admin_session_ttl_hours",
            value=9999,
            previous_value=8,
            source="user",
            updated_at=utc_now(),
            updated_by_user_id=None,
        )
    )
    assert read_stored_parameter("admin_session_ttl_hours").value == 9999


def test_resolve_int_returns_nearest_bound() -> None:
    assemble_system_parameters()
    store = get_parameter_store()
    store.upsert(
        ParameterRecord(
            key="admin_session_ttl_hours",
            value=9999,
            previous_value=8,
            source="user",
            updated_at=utc_now(),
            updated_by_user_id=None,
        )
    )
    assert resolve_int("admin_session_ttl_hours").value == 168
    assert resolve_int("admin_session_ttl_hours").previous_value == 8


def test_unrecognised_source_takes_read_failure_path() -> None:
    assemble_system_parameters()
    set_parameter("admin_session_ttl_hours", 12, actor_user_id=None)
    assert read_stored_parameter("admin_session_ttl_hours").value == 12
    store = get_parameter_store()
    existing = store.get("admin_session_ttl_hours")
    assert existing is not None
    store.upsert(
        ParameterRecord(
            key=existing.key,
            value=12,
            previous_value=existing.previous_value,
            source="legacy",
            updated_at=existing.updated_at,
            updated_by_user_id=existing.updated_by_user_id,
        )
    )
    with pytest.raises(ParameterReadFailed):
        read_stored_parameter("admin_session_ttl_hours")

    resolved = resolve_int("admin_session_ttl_hours")
    assert resolved.value == 12
    assert resolved.source == "user"

    clear_last_known()
    degraded = resolve_int("admin_session_ttl_hours")
    assert degraded.value == 8
    assert degraded.source == "seed"
    assert degraded.updated_at is None


def test_optional_int_constraint_admits_none_without_substituting() -> None:
    reset_parameter_registry()
    spec = ParameterSpec(
        key="optional_test_key",
        constraint=IntConstraint(minimum=1, optional=True),
        seed=None,
        owner="admin",
        group="session",
        operator_action_required=False,
        apply_note_key="settings.parameter.admin_session_ttl_hours.apply",
        label_key="settings.parameter.admin_session_ttl_hours.label",
        help_key="settings.parameter.admin_session_ttl_hours.help",
    )
    try:
        register_parameters((spec,), group_order=("session",))
        fragment = spec.constraint.to_json_schema()
        assert fragment["type"] == ["integer", "null"]
        assert spec.constraint.admit(None) is True
        assert spec.constraint.fallback(None, spec.seed) is None
    finally:
        reset_parameter_registry()
        assemble_system_parameters()


def test_constraint_fragment_uses_only_profile_keywords() -> None:
    assemble_system_parameters()
    for spec in list_registered_specs():
        keys = set(spec.constraint.to_json_schema())
        assert keys <= JSON_SCHEMA_PROFILE_KEYWORDS


def test_registry_parity_across_composition() -> None:
    assemble_system_parameters()
    declared = {
        spec.key for spec in (*ADMIN_PARAMETER_SPECS, *JOBS_PARAMETER_SPECS)
    }
    assert {spec.key for spec in list_registered_specs()} == declared
    main_src = (BACKEND_ROOT / "main.py").read_text(encoding="utf-8")
    app_src = (BACKEND_ROOT / "worker" / "app.py").read_text(encoding="utf-8")
    upgrade_src = (BACKEND_ROOT / "core" / "upgrade.py").read_text(encoding="utf-8")
    assert "assemble_system_parameters" in main_src
    assert "assemble_system_parameters" in app_src
    assert "assemble_system_parameters" in upgrade_src


def test_retired_keys_are_not_registered() -> None:
    assemble_system_parameters()
    keys = {spec.key for spec in list_registered_specs()}
    assert "job_worker_concurrency" not in keys
    assert "beat_sync_every_sec" not in keys
    assert "beat_max_interval_sec" not in keys
    assert "reaper_interval_sec" not in keys
    app_src = (BACKEND_ROOT / "worker" / "app.py").read_text(encoding="utf-8")
    assert "worker_concurrency" not in app_src
    for key in (
        "job_worker_concurrency",
        "beat_sync_every_sec",
        "beat_max_interval_sec",
        "reaper_interval_sec",
    ):
        with pytest.raises(UnregisteredParameter):
            get_parameter_spec(key)


def test_settings_has_no_registered_key_env_alias() -> None:
    assemble_system_parameters()
    names: set[str] = set()
    for field in Settings.model_fields.values():
        names.update(_alias_strings(field))
    for spec in list_registered_specs():
        assert spec.key.upper() not in names
        assert f"REFRAQ_{spec.key.upper()}" not in names


def test_env_example_has_no_registered_key_names() -> None:
    assemble_system_parameters()
    text = (BACKEND_ROOT / ".env.example").read_text(encoding="utf-8")
    for spec in list_registered_specs():
        assert spec.key.upper() not in text
        assert f"REFRAQ_{spec.key.upper()}" not in text


def test_leftover_env_name_is_logged(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    assemble_system_parameters()
    monkeypatch.setenv("ADMIN_SESSION_TTL_HOURS", "12")
    monkeypatch.setenv("REFRAQ_JOB_WORKER_CONCURRENCY", "4")
    with caplog.at_level(logging.WARNING, logger="backend.worker.parameters"):
        assemble_system_parameters()
    assert "ADMIN_SESSION_TTL_HOURS" in caplog.text
    assert "admin_session_ttl_hours" in caplog.text
    assert "REFRAQ_JOB_WORKER_CONCURRENCY" not in caplog.text


def _alias_strings(field: FieldInfo) -> set[str]:
    alias = field.validation_alias
    if alias is None:
        return set()
    if isinstance(alias, str):
        return {alias}
    choices = getattr(alias, "choices", None)
    if choices is None:
        return {str(alias)}
    return {item for item in choices if isinstance(item, str)}


def test_mechanism_has_no_domain_vocabulary() -> None:
    forbidden = (
        "occupancy",
        "lost_detection",
        "job_lost",
        "reaper",
        "admin_session",
        "session_ttl",
    )
    root = BACKEND_ROOT / "admin" / "system_parameters"
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for word in forbidden:
            assert word not in text, f"{path} contains {word}"


def test_tighten_lost_detection_waits_old_renew_interval() -> None:
    assemble_system_parameters()
    clock = FixedClock(parse_instant("2026-08-17T10:00:00Z"))
    set_clock(clock)
    try:
        job = create_queued_job(kind="structure", input={"source_id": "src_1"})
        claimed = claim_queued(job.id, claimed_by="w1")
        assert claimed is not None
        stored = get_job_store().get(job.id)
        assert stored is not None
        stored.locked_at = clock.now() - timedelta(seconds=40)
        get_job_store().save(stored)

        set_parameter("job_lost_detection_sec", 15, actor_user_id=None)
        assert reaper_lost_detection_sec() == 60
        assert reap_stale_occupancy() == 0
        stored = get_job_store().get(job.id)
        assert stored is not None
        assert stored.status == "running"

        clock.advance(timedelta(seconds=20))
        assert reaper_lost_detection_sec() == 15
        assert reap_stale_occupancy() == 1
        stored = get_job_store().get(job.id)
        assert stored is not None
        assert stored.status == "failed"
        assert stored.error_code == ERROR_WORKER_LOST
    finally:
        reset_clock()


def test_widen_lost_detection_is_immediate() -> None:
    assemble_system_parameters()
    clock = FixedClock(parse_instant("2026-08-17T10:00:00Z"))
    set_clock(clock)
    try:
        job = create_queued_job(kind="structure", input={"source_id": "src_1"})
        claimed = claim_queued(job.id, claimed_by="w1")
        assert claimed is not None
        stored = get_job_store().get(job.id)
        assert stored is not None
        stored.locked_at = clock.now() - timedelta(seconds=90)
        get_job_store().save(stored)

        set_parameter("job_lost_detection_sec", 120, actor_user_id=None)
        assert reaper_lost_detection_sec() == 120
        assert reap_stale_occupancy() == 0
        stored = get_job_store().get(job.id)
        assert stored is not None
        assert stored.status == "running"
    finally:
        reset_clock()


def test_reaper_interval_follows_lost_detection() -> None:
    assemble_system_parameters()
    reset_system_parameters()
    ensure_system_schedules()
    record = get_schedule_store().get_by_key(REAPER_SCHEDULE_KEY)
    assert record is not None
    assert record.interval_seconds == 60

    set_parameter("job_lost_detection_sec", 90, actor_user_id=None)
    ensure_system_schedules()
    updated = get_schedule_store().get_by_key(REAPER_SCHEDULE_KEY)
    assert updated is not None
    assert updated.interval_seconds == 90


def test_last_known_good_after_store_failure() -> None:
    assemble_system_parameters()
    set_parameter("admin_session_ttl_hours", 12, actor_user_id=None)
    store = get_parameter_store()
    original_get = store.get

    def boom(key: str) -> ParameterRecord | None:
        raise RuntimeError("store down")

    store.get = boom  # type: ignore[method-assign]
    try:
        with pytest.raises(ParameterReadFailed):
            read_stored_parameter("admin_session_ttl_hours")
        assert resolve_int("admin_session_ttl_hours").value == 12
    finally:
        store.get = original_get  # type: ignore[method-assign]
        reset_parameter("admin_session_ttl_hours", actor_user_id=None)


def test_never_read_uses_code_seed_when_store_fails() -> None:
    assemble_system_parameters()
    clear_last_known()
    store = get_parameter_store()
    original_get = store.get

    def boom(key: str) -> ParameterRecord | None:
        raise RuntimeError("store down")

    store.get = boom  # type: ignore[method-assign]
    try:
        with pytest.raises(ParameterReadFailed):
            read_stored_parameter("admin_session_ttl_hours")
        resolved = resolve_int("admin_session_ttl_hours")
        assert resolved.value == 8
        assert resolved.source == "seed"
        assert resolved.updated_at is None
    finally:
        store.get = original_get  # type: ignore[method-assign]
