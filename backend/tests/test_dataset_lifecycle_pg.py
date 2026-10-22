"""Dataset expiry sealing, purge, and orphan tables."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text

from backend.channel.dataset_registry import (
    DatasetRecord,
    DatasetRegistry,
    get_dataset_store,
    reset_dataset_store,
)
from backend.channel.run_store import ChannelRunRecord, get_run_store
from backend.core.config import reset_settings_cache
from backend.core.time import FixedClock, set_clock, utc_now
from backend.entity.datasets import physical_relation
from backend.entity.entity_db import get_entity_engine, reset_entity_engine
from backend.tests.entity_pg import bootstrapped_entity_database
from backend.admin.system_parameters import set_parameter
from backend.jobs.store import (
    claim_for_execution,
    create_queued_job,
    get_job_store,
    mark_cancelled,
    mark_failed,
    mark_succeeded,
)
from backend.worker.parameters import assemble_system_parameters

_MAINTENANCE_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)
_INTEGRATION_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq_test",
)

# Independent of the retention arithmetic in production code.
_FINISHED = datetime(2026, 1, 15, 8, 30, tzinfo=timezone.utc)
_SUCCESS_EXPIRES = datetime(2026, 1, 16, 8, 30, tzinfo=timezone.utc)
_DAYS_EXPIRES = datetime(2026, 1, 22, 8, 30, tzinfo=timezone.utc)

pytestmark = pytest.mark.integration


def _postgres_available() -> bool:
    try:
        engine = create_engine(_MAINTENANCE_DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


def _reset_run_store() -> None:
    import backend.channel.run_store as run_store

    with run_store._lock:
        run_store._memory = None


@pytest.fixture
def lifecycle() -> None:
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")
    assemble_system_parameters()
    set_clock(FixedClock(_FINISHED))
    _reset_run_store()
    reset_dataset_store()
    yield
    _reset_run_store()
    reset_dataset_store()


@pytest.fixture
def sql_platform(monkeypatch: pytest.MonkeyPatch):
    """Platform registry, jobs, and runs on the integration database."""
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")
    try:
        engine = create_engine(_INTEGRATION_DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
    except Exception:
        pytest.skip("platform integration database not available")
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "persistent")
    monkeypatch.setenv("DATABASE_URL", _INTEGRATION_DATABASE_URL)
    from backend.admin.system_parameters import reset_parameter
    from backend.channel.models import ChannelDatasetRow, ChannelNodeExecutionRow, ChannelRunRow
    from backend.core.db import reset_db_singletons, session_scope
    from backend.core.entry import migrate_with_advisory_lock
    from backend.jobs.models import JobRow
    from backend.jobs.store import reset_job_store
    from sqlalchemy import delete

    reset_settings_cache()
    reset_db_singletons()
    reset_job_store()
    reset_dataset_store()
    _reset_run_store()
    migrate_with_advisory_lock(_INTEGRATION_DATABASE_URL)
    assemble_system_parameters()
    set_clock(FixedClock(_FINISHED))
    job_ids: list[str] = []
    try:
        yield job_ids
    finally:
        with session_scope() as session:
            session.execute(delete(ChannelDatasetRow).where(ChannelDatasetRow.id == "dsealsql1"))
            if job_ids:
                session.execute(
                    delete(ChannelNodeExecutionRow).where(
                        ChannelNodeExecutionRow.job_id.in_(job_ids)
                    )
                )
                session.execute(
                    delete(ChannelDatasetRow).where(ChannelDatasetRow.job_id.in_(job_ids))
                )
                session.execute(
                    delete(ChannelRunRow).where(ChannelRunRow.job_id.in_(job_ids))
                )
                session.execute(delete(JobRow).where(JobRow.id.in_(job_ids)))
        reset_parameter("channel_dataset_success_retention_hours", actor_user_id=None)
        reset_parameter("channel_dataset_retention_days", actor_user_id=None)
        reset_job_store()
        reset_dataset_store()
        _reset_run_store()
        reset_db_singletons()
        reset_settings_cache()


@pytest.fixture
def entity_lifecycle(lifecycle: None, monkeypatch: pytest.MonkeyPatch):
    with bootstrapped_entity_database(_MAINTENANCE_DATABASE_URL, "refraq_dslife") as urls:
        monkeypatch.setenv("ENTITY_DATABASE_URL", urls.owner_url)
        monkeypatch.setenv("ENTITY_READER_DATABASE_URL", urls.reader_url)
        reset_settings_cache()
        reset_entity_engine()
        try:
            yield
        finally:
            reset_entity_engine()
            reset_settings_cache()


def _insert_run(job_id: str, target: str, *, created_at: datetime | None = None) -> None:
    get_run_store().insert_run(
        ChannelRunRecord(
            job_id=job_id,
            channel_id="chn_lifecycle",
            target=target,
            version=1 if target == "published" else None,
            draft_revision=None if target == "published" else 1,
            graph=None,
            trigger_node_id="nd_trigger",
            ignore_checkpoints=False,
            outcome=None,
            failed_node_id=None,
            skipped_node_ids=[],
            created_at=created_at or utc_now(),
        )
    )


def _insert_dataset(job_id: str, dataset_id: str) -> None:
    get_dataset_store().save(
        DatasetRecord(
            id=dataset_id,
            job_id=job_id,
            node_id="nd_read",
            seq=1,
            relation=physical_relation(dataset_id),
            columns=[{"name": "n", "type": "bigint", "normalized_type": "integer"}],
            row_count=1,
            size_bytes=1,
            status="ready",
            created_at=utc_now(),
            expires_at=None,
        )
    )


def _succeeded_job() -> str:
    job = create_queued_job(
        kind="channel_run",
        input={"channel_id": "chn_lifecycle"},
        summary="lifecycle",
    )
    assert claim_for_execution(job.id, claimed_by="test") is not None
    assert mark_succeeded(job.id, result={"schema": "channel_run.v1"}) is not None
    return job.id


def test_succeeded_published_run_seals_success_hours(lifecycle: None) -> None:
    from backend.channel.dataset_registry import seal_dataset_expiry

    job_id = _succeeded_job()
    _insert_run(job_id, "published")
    _insert_dataset(job_id, "dsealpub")
    seal_dataset_expiry(job_id)
    stored = get_dataset_store().get("dsealpub")
    assert stored is not None
    assert stored.expires_at == _SUCCESS_EXPIRES


def test_failed_run_seals_retention_days(lifecycle: None) -> None:
    from backend.channel.dataset_registry import seal_dataset_expiry

    job = create_queued_job(
        kind="channel_run",
        input={"channel_id": "chn_lifecycle"},
        summary="lifecycle",
    )
    assert (
        mark_failed(job.id, error_code="CHANNEL_NODE_FAILED", error_summary="failed")
        is not None
    )
    _insert_run(job.id, "published")
    _insert_dataset(job.id, "dsealfail")
    seal_dataset_expiry(job.id)
    stored = get_dataset_store().get("dsealfail")
    assert stored is not None
    assert stored.expires_at == _DAYS_EXPIRES


def test_succeeded_draft_run_seals_retention_days(lifecycle: None) -> None:
    from backend.channel.dataset_registry import seal_dataset_expiry

    job_id = _succeeded_job()
    _insert_run(job_id, "draft")
    _insert_dataset(job_id, "dsealdraft")
    seal_dataset_expiry(job_id)
    stored = get_dataset_store().get("dsealdraft")
    assert stored is not None
    assert stored.expires_at == _DAYS_EXPIRES


def test_cancelled_run_seals_retention_days(lifecycle: None) -> None:
    from backend.channel.dataset_registry import seal_dataset_expiry

    job = create_queued_job(
        kind="channel_run",
        input={"channel_id": "chn_lifecycle"},
        summary="lifecycle",
    )
    assert mark_cancelled(job.id) is not None
    _insert_run(job.id, "published")
    _insert_dataset(job.id, "dsealcancel")
    seal_dataset_expiry(job.id)
    stored = get_dataset_store().get("dsealcancel")
    assert stored is not None
    assert stored.expires_at == _DAYS_EXPIRES


def test_zero_success_hours_is_due_at_finished_at(lifecycle: None) -> None:
    from backend.channel.dataset_registry import seal_dataset_expiry

    set_parameter("channel_dataset_success_retention_hours", 0, actor_user_id=None)
    job_id = _succeeded_job()
    _insert_run(job_id, "published")
    _insert_dataset(job_id, "dsealzero")
    seal_dataset_expiry(job_id)
    stored = get_dataset_store().get("dsealzero")
    assert stored is not None
    assert stored.expires_at == _FINISHED


def test_second_seal_keeps_the_timestamp_after_a_parameter_change(lifecycle: None) -> None:
    from backend.channel.dataset_registry import seal_dataset_expiry

    job_id = _succeeded_job()
    _insert_run(job_id, "published")
    _insert_dataset(job_id, "dsealonce")
    seal_dataset_expiry(job_id)
    set_parameter("channel_dataset_success_retention_hours", 1, actor_user_id=None)
    seal_dataset_expiry(job_id)
    stored = get_dataset_store().get("dsealonce")
    assert stored is not None
    assert stored.expires_at == _SUCCESS_EXPIRES


def test_non_terminal_run_stays_unsealed(lifecycle: None) -> None:
    from backend.channel.dataset_registry import seal_dataset_expiry

    job = create_queued_job(
        kind="channel_run",
        input={"channel_id": "chn_lifecycle"},
        summary="lifecycle",
    )
    assert claim_for_execution(job.id, claimed_by="test") is not None
    _insert_run(job.id, "published")
    _insert_dataset(job.id, "dsealrun")
    seal_dataset_expiry(job.id)
    stored = get_dataset_store().get("dsealrun")
    assert stored is not None
    assert stored.expires_at is None


def test_sql_registry_seals_success_hours_once(sql_platform: list[str]) -> None:
    from backend.channel.dataset_registry import seal_dataset_expiry

    job_id = _succeeded_job()
    sql_platform.append(job_id)
    # No channel run row: the target is not draft, so success hours apply.
    _insert_dataset(job_id, "dsealsql1")
    seal_dataset_expiry(job_id)
    set_parameter("channel_dataset_success_retention_hours", 1, actor_user_id=None)
    seal_dataset_expiry(job_id)
    stored = get_dataset_store().get("dsealsql1")
    assert stored is not None
    assert stored.expires_at == _SUCCESS_EXPIRES
    assert stored.status == "ready"


def test_retention_schedule_identity_stays_on_the_run_record_task() -> None:
    from backend.channel.parameters import RUN_RECORD_SCHEDULE_KEY, RUN_RECORD_TASK_NAME

    assert RUN_RECORD_SCHEDULE_KEY == "channel_run_record_retention"
    assert RUN_RECORD_TASK_NAME == "backend.channel.tasks.purge_run_records"


def test_purge_seals_a_terminal_dataset_the_runner_missed(entity_lifecycle: None) -> None:
    from backend.channel.tasks import purge_expired_run_records

    job = create_queued_job(
        kind="channel_run",
        input={"channel_id": "chn_lifecycle"},
        summary="lifecycle",
    )
    assert (
        mark_failed(job.id, error_code="JOB_WORKER_LOST", error_summary="worker lost")
        is not None
    )
    _insert_run(job.id, "published")
    _insert_dataset(job.id, "dseallate")
    deleted = purge_expired_run_records()
    assert deleted == 0
    stored = get_dataset_store().get("dseallate")
    assert stored is not None
    assert stored.status == "ready"
    assert stored.expires_at == _DAYS_EXPIRES
    assert get_run_store().get_run(job.id) is not None


def test_reaper_seals_a_job_it_marks_worker_lost(lifecycle: None) -> None:
    from backend.worker.tasks import reap_stuck_jobs

    job = create_queued_job(
        kind="channel_run",
        input={"channel_id": "chn_lifecycle"},
        summary="lifecycle",
    )
    assert claim_for_execution(job.id, claimed_by="worker-a") is not None
    running = get_job_store().get(job.id)
    assert running is not None
    running.locked_at = _FINISHED - timedelta(seconds=120)
    get_job_store().save(running)
    _insert_run(job.id, "published")
    _insert_dataset(job.id, "dsealreap")
    assert reap_stuck_jobs() == {"reaped": 1}
    stored = get_dataset_store().get("dsealreap")
    assert stored is not None
    assert stored.expires_at == _DAYS_EXPIRES


def test_parent_run_job_seals_when_the_job_is_already_terminal(lifecycle: None) -> None:
    from backend.channel.tasks import run_job

    job = create_queued_job(
        kind="channel_run",
        input={"channel_id": "chn_lifecycle"},
        summary="lifecycle",
    )
    assert mark_cancelled(job.id) is not None
    _insert_run(job.id, "published")
    _insert_dataset(job.id, "dsealparent")
    assert run_job(job.id) == {"status": "cancelled"}
    stored = get_dataset_store().get("dsealparent")
    assert stored is not None
    assert stored.expires_at == _DAYS_EXPIRES


def test_runner_seals_when_it_cancels_a_job_without_a_run(lifecycle: None) -> None:
    from backend.channel.runner import run_channel_job

    job = create_queued_job(
        kind="channel_run",
        input={"channel_id": "chn_lifecycle"},
        summary="lifecycle",
    )
    _insert_dataset(job.id, "dsealnorun")
    assert run_channel_job(job.id) == {"status": "cancelled"}
    stored = get_dataset_store().get("dsealnorun")
    assert stored is not None
    assert stored.expires_at == _DAYS_EXPIRES


def test_runner_seals_success_hours_after_a_published_run(lifecycle: None) -> None:
    from backend.channel.channel_run import mint_on_demand_run
    from backend.channel.ids import new_channel_id
    from backend.channel.runner import run_channel_job
    from backend.channel.store import ChannelRecord, get_channel_store

    graph = {
        "nodes": [
            {
                "id": "nd_trigger",
                "ref": "run_manually",
                "type": "trigger.manual",
                "name": "Run manually",
                "position": {"x": 0, "y": 0},
                "config": {},
                "on_error": "stop",
                "retry": None,
            }
        ],
        "edges": [],
        "settings": {
            "run_timeout_sec": None,
            "run_retry_limit": None,
            "error_channel_id": None,
        },
    }
    now = utc_now()
    channels = get_channel_store()
    created = channels.create(
        ChannelRecord(
            id=new_channel_id(),
            name="Lifecycle",
            description=None,
            active=True,
            draft_graph={"nodes": [], "edges": [], "settings": {}},
            draft_revision=1,
            draft_updated_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    drafted = channels.replace_draft(created.id, base_revision=1, graph=graph, now=now)
    channels.publish_version(
        created.id,
        draft_revision=drafted.draft_revision,
        published_at=now,
        published_by_user_id="usr_test",
    )
    job, _run = mint_on_demand_run(
        channel_id=created.id,
        channel_name=created.name,
        target="published",
        ignore_checkpoints=False,
        actor_id="usr_test",
        trigger_node_id="nd_trigger",
        version=1,
        draft_revision=None,
        graph=None,
        stop_at_node_id=None,
    )
    _insert_dataset(job.id, "dsealrunok")
    assert run_channel_job(job.id) == {"status": "succeeded"}
    stored = get_dataset_store().get("dsealrunok")
    assert stored is not None
    assert stored.expires_at == _SUCCESS_EXPIRES


def _relation_exists(relation: str) -> bool:
    with get_entity_engine().connect() as conn:
        found = conn.execute(
            text("SELECT to_regclass(:name)"),
            {"name": relation},
        ).scalar_one()
    return found is not None


def test_purge_drops_the_physical_table_with_a_due_run(entity_lifecycle: None) -> None:
    from backend.channel.tasks import purge_expired_run_records

    created_at = datetime(2025, 12, 15, 8, 30, tzinfo=timezone.utc)
    job = create_queued_job(
        kind="channel_run",
        input={"channel_id": "chn_lifecycle"},
        summary="lifecycle",
        created_at=created_at,
    )
    assert claim_for_execution(job.id, claimed_by="test") is not None
    assert mark_succeeded(job.id, result={"schema": "channel_run.v1"}) is not None
    _insert_run(job.id, "published", created_at=created_at)
    record = DatasetRegistry(get_dataset_store()).create_from_query(
        job_id=job.id,
        node_id="nd_read",
        seq=1,
        query="SELECT 1 AS n",
    )
    execution = get_run_store().start_execution(job.id, "nd_read")
    execution.status = "succeeded"
    execution.finished_at = _FINISHED
    execution.output = {"n": 1}
    execution.output_bytes = 1
    get_run_store().finish_execution(execution)
    assert _relation_exists(record.relation)

    assert purge_expired_run_records() == 1
    assert get_run_store().get_run(job.id) is None
    assert get_run_store().list_executions(job.id) == []
    assert get_job_store().get(job.id) is not None
    stored = get_dataset_store().get(record.id)
    assert stored is not None
    assert stored.status == "dropped"
    assert _relation_exists(record.relation) is False


def test_purge_drops_an_expired_dataset_while_the_run_remains(entity_lifecycle: None) -> None:
    from backend.channel.tasks import purge_expired_run_records

    job_id = _succeeded_job()
    _insert_run(job_id, "published")
    record = DatasetRegistry(get_dataset_store()).create_from_query(
        job_id=job_id,
        node_id="nd_read",
        seq=1,
        query="SELECT 1 AS n",
    )
    set_clock(FixedClock(datetime(2026, 1, 17, 8, 30, tzinfo=timezone.utc)))
    assert purge_expired_run_records() == 0
    stored = get_dataset_store().get(record.id)
    assert stored is not None
    assert stored.expires_at == _SUCCESS_EXPIRES
    assert stored.status == "dropped"
    assert _relation_exists(record.relation) is False
    assert get_run_store().get_run(job_id) is not None


def test_purge_keeps_a_loading_dataset_while_the_run_is_not_terminal(
    entity_lifecycle: None,
) -> None:
    from backend.channel.tasks import purge_expired_run_records

    job = create_queued_job(
        kind="channel_run",
        input={"channel_id": "chn_lifecycle"},
        summary="lifecycle",
    )
    assert claim_for_execution(job.id, claimed_by="test") is not None
    _insert_run(job.id, "draft")
    record = DatasetRegistry(get_dataset_store()).create_from_query(
        job_id=job.id,
        node_id="nd_read",
        seq=1,
        query="SELECT 1 AS n",
    )
    current = get_dataset_store().get(record.id)
    assert current is not None
    current.status = "loading"
    current.expires_at = datetime(2026, 1, 14, 8, 30, tzinfo=timezone.utc)
    get_dataset_store().save(current)
    assert purge_expired_run_records() == 0
    stored = get_dataset_store().get(record.id)
    assert stored is not None
    assert stored.status == "loading"
    assert stored.expires_at == datetime(2026, 1, 14, 8, 30, tzinfo=timezone.utc)
    assert _relation_exists(record.relation) is True


def test_purge_drops_a_loading_dataset_once_the_run_is_terminal(
    entity_lifecycle: None,
) -> None:
    from backend.channel.tasks import purge_expired_run_records

    job_id = _succeeded_job()
    _insert_run(job_id, "draft")
    record = DatasetRegistry(get_dataset_store()).create_from_query(
        job_id=job_id,
        node_id="nd_read",
        seq=1,
        query="SELECT 1 AS n",
    )
    current = get_dataset_store().get(record.id)
    assert current is not None
    current.status = "loading"
    current.expires_at = datetime(2026, 1, 14, 8, 30, tzinfo=timezone.utc)
    get_dataset_store().save(current)
    assert purge_expired_run_records() == 0
    stored = get_dataset_store().get(record.id)
    assert stored is not None
    assert stored.status == "dropped"
    assert _relation_exists(record.relation) is False


def test_purge_drops_orphan_dataset_tables_and_keeps_unrelated_ones(
    entity_lifecycle: None,
) -> None:
    from backend.channel.tasks import purge_expired_run_records
    from backend.entity.datasets import create_table_from_query

    job_id = _succeeded_job()
    _insert_run(job_id, "published")
    kept = DatasetRegistry(get_dataset_store()).create_from_query(
        job_id=job_id,
        node_id="nd_read",
        seq=1,
        query="SELECT 1 AS n",
    )
    orphan = physical_relation("dorphan1")
    create_table_from_query(orphan, "SELECT 2 AS n")
    get_dataset_store().save(
        DatasetRecord(
            id="dorphan1",
            job_id=job_id,
            node_id="nd_read",
            seq=2,
            relation=orphan,
            columns=[],
            row_count=1,
            size_bytes=1,
            status="dropped",
            created_at=_FINISHED,
            expires_at=None,
        )
    )
    with get_entity_engine().begin() as conn:
        conn.exec_driver_sql("CREATE TABLE channel_dataset.keep_notes (id int)")
        conn.exec_driver_sql('CREATE TABLE channel_dataset."dsXkeep" (id int)')
        conn.exec_driver_sql("CREATE TABLE entity_data.ds_decoy (id int)")
    assert purge_expired_run_records() == 0
    assert _relation_exists(orphan) is False
    assert _relation_exists(kept.relation) is True
    assert _relation_exists('"channel_dataset"."keep_notes"') is True
    assert _relation_exists('"channel_dataset"."dsXkeep"') is True
    assert _relation_exists('"entity_data"."ds_decoy"') is True
