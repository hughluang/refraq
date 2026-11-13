"""catalog_embed run-log progress, deduplicated failures, and cooperative cancel."""

from __future__ import annotations

from dataclasses import replace

import pytest

from backend.admin.model_services import get_embedding_runtime, mark_embedding_ready
from backend.metadata.catalog.index_state import (
    get_catalog_index_store,
    note_catalog_index_failure,
    publish_catalog_readiness,
)

from backend.admin.model_services.records import ModelServiceRecord, PurposeState
from backend.admin.model_services.store import get_model_service_store
from backend.core.time import utc_now
from backend.jobs.store import (
    create_queued_job,
    get_job_store,
    mark_cancelled,
)
from backend.metadata.catalog.embedding import set_embed_fn_for_tests
from backend.metadata.catalog.index_embeddings import EmbeddingRefreshCounts
from backend.metadata.catalog.records import CatalogColumnRecord, CatalogObjectRecord
from backend.metadata.catalog.structure_refresh import apply_structure_snapshot
from backend.metadata.catalog_embed_jobs.progress_log import (
    LOAD_EVERY,
    MAX_DISTINCT_REASONS,
    PROGRESS_EVERY,
    CatalogEmbedLog,
)
from backend.metadata.catalog_embed_jobs.runner import _deadline_stop, run_catalog_embed_job
from backend.metadata.sources.service import require_source
from backend.metadata.sources.store import SourceRecord, get_source_store


def _messages(job_id: str) -> list[str]:
    stored = get_job_store().get(job_id)
    assert stored is not None
    out: list[str] = []
    for line in stored.log_body.splitlines():
        parts = line.split(" ", 2)
        assert len(parts) == 3
        out.append(f"{parts[1]} {parts[2]}")
    return out


def _counts(*, written: int = 0, failed: int = 0, skipped: int = 0) -> EmbeddingRefreshCounts:
    return EmbeddingRefreshCounts(
        objects_written=written,
        objects_failed=failed,
        objects_skipped=skipped,
    )


def test_deadline_stop_only_when_timeouts_exceed_writes() -> None:
    assert (
        _deadline_stop(
            EmbeddingRefreshCounts(objects_written=3, timeout_failed=1),
            dominant=None,
        )
        is None
    )
    assert (
        _deadline_stop(
            EmbeddingRefreshCounts(objects_written=2, timeout_failed=2),
            dominant="timed out",
        )
        is None
    )
    over = EmbeddingRefreshCounts(objects_written=1, timeout_failed=2)
    assert _deadline_stop(over, dominant=None) == (
        "catalog_embed stopped: embedding timeouts exceed writes"
    )
    summary = _deadline_stop(over, dominant="timed out after 30s")
    assert summary == (
        "catalog_embed stopped: embedding timeouts exceed writes: timed out after 30s"
    )


def test_progress_throttles_heartbeats() -> None:
    job = create_queued_job(kind="catalog_embed", input={})
    log = CatalogEmbedLog(job.id)
    log.start_source("embed-src")
    log.planned(objects=10, columns=290)
    log.progressed(_counts(written=32), processed=32, total=300)
    log.progressed(_counts(written=64), processed=64, total=300)
    log.progressed(_counts(written=PROGRESS_EVERY), processed=PROGRESS_EVERY, total=300)
    log.progressed(_counts(written=300), processed=300, total=300)
    assert _messages(job.id) == [
        "INFO indexing embed-src…",
        "INFO indexing embed-src: 10 objects, 290 columns",
        "INFO embed-src 32/300 written=32 failed=0 skipped=0",
        f"INFO embed-src {PROGRESS_EVERY}/300 written={PROGRESS_EVERY} failed=0 skipped=0",
        "INFO embed-src 300/300 written=300 failed=0 skipped=0",
    ]


def test_loading_reports_listed_then_throttled_counts() -> None:
    job = create_queued_job(kind="catalog_embed", input={})
    log = CatalogEmbedLog(job.id)
    log.start_source("embed-src")
    log.loading(objects=200, loaded=0)
    log.loading(objects=200, loaded=LOAD_EVERY)
    log.loading(objects=200, loaded=200)
    log.planned(objects=200, columns=10)
    messages = _messages(job.id)
    assert messages.index("INFO loading embed-src: 200 objects…") < messages.index(
        f"INFO loading embed-src: {LOAD_EVERY}/200 objects"
    )
    assert messages.index("INFO loading embed-src: 200/200 objects") < messages.index(
        "INFO indexing embed-src: 200 objects, 10 columns"
    )


def test_failed_reason_logs_first_then_flush_count() -> None:
    job = create_queued_job(kind="catalog_embed", input={})
    log = CatalogEmbedLog(job.id)
    reason = "Embeddings HTTP 400 at http://embed: bad"
    log.failed(reason=reason, n=32)
    log.failed(reason=reason, n=32)
    log.flush_reason_counts()
    assert _messages(job.id) == [
        f"WARN embed failed ×32: {reason}",
        f"WARN embed failed ×64: {reason}",
    ]
    assert log.failure_reasons() == [{"message": reason, "count": 64}]
    assert log.dominant_reason() == reason
    assert log.dominant_count() == 64


def test_distinct_reasons_cap_omits_overflow() -> None:
    job = create_queued_job(kind="catalog_embed", input={})
    log = CatalogEmbedLog(job.id)
    for i in range(MAX_DISTINCT_REASONS + 2):
        log.failed(reason=f"err-{i}", n=1)
    log.flush_reason_counts()
    messages = _messages(job.id)
    assert sum(1 for line in messages if line.startswith("WARN embed failed")) == (
        MAX_DISTINCT_REASONS
    )
    assert "WARN +2 distinct embed errors omitted" in messages
    assert len(log.failure_reasons()) == MAX_DISTINCT_REASONS


def _seed_source(*, object_count: int, columns_per_object: int) -> str:
    source_id = "src_embed"
    now = utc_now()
    get_source_store().create_source(
        SourceRecord(
            id=source_id,
            key="embed-src",
            locator_key="src/postgresql/embed-src",
            name="Embed",
            kind="database",
            status="active",
            description=None,
            engine="postgresql",
            access_ciphertext=None,
            access_updated_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    collected: list[CatalogObjectRecord] = []
    for i in range(object_count):
        obj_id = f"obj_{i}"
        columns = [
            CatalogColumnRecord(
                id=f"col_{i}_{j}",
                object_id=obj_id,
                locator_key=f"col/postgresql/embed-src/public/table/t{i}/column/c{j}",
                name=f"c{j}",
                ordinal=j,
                data_type="int",
                nullable=False,
                is_present=True,
                default_value=None,
                comment=None,
                business_name=None,
                business_description=None,
                column_semantics=None,
                enum_catalog=None,
                semantic_source=None,
                field_kind="column",
                created_at=now,
                updated_at=now,
            )
            for j in range(columns_per_object)
        ]
        collected.append(
            CatalogObjectRecord(
                id=obj_id,
                source_id=source_id,
                locator_key=f"obj/postgresql/embed-src/public/table/t{i}",
                object_type="table",
                schema_name="public",
                name=f"t{i}",
                ddl=None,
                comment=None,
                primary_key=None,
                is_present=True,
                business_name=None,
                business_description=None,
                object_category=None,
                grain_description=None,
                business_primary_key=None,
                evidence_summary=None,
                open_questions=None,
                semantic_source=None,
                business_semantics_ready=False,
                semantics_updated_at=None,
                last_structure_job_id=None,
                collected_at=now,
                created_at=now,
                updated_at=now,
                columns=columns,
            )
        )
    apply_structure_snapshot(
        source=require_source(source_id),
        job_id="job_embed_seed",
        collected=collected,
        schema_scope=None,
    )
    return source_id


def _seed_embedding_runtime() -> None:
    now = utc_now()
    store = get_model_service_store()
    store.save(
        ModelServiceRecord(
            id="msvc_test",
            purpose="embedding",
            protocol="openai_compat",
            display_name="test",
            url="http://embed.test/v1/embeddings",
            model="m",
            timeout_sec=30,
            secret=None,
            created_at=now,
            updated_at=now,
        )
    )
    store.save_purpose(
        PurposeState(
            purpose="embedding",
            in_use_id="msvc_test",
            closed=False,
            ready=False,
            generation=1,
        )
    )


def _run_embed(*, embed_fn) -> object:
    _seed_embedding_runtime()
    set_embed_fn_for_tests(embed_fn)
    job = create_queued_job(kind="catalog_embed", input={})
    run_catalog_embed_job(job.id)
    record = get_job_store().get(job.id)
    assert record is not None
    set_embed_fn_for_tests(None)
    return record


@pytest.mark.parametrize("field", ["in_use_id", "generation", "control_revision"])
def test_shared_fence_rejection_does_not_execute_callback(monkeypatch, field) -> None:
    _seed_embedding_runtime()
    store = get_model_service_store()
    state = store.get_purpose("embedding")
    stale = replace(state, **{field: "other_service" if field == "in_use_id" else 99})
    store.save_purpose(stale)
    callbacks = []
    writes = []
    monkeypatch.setattr(store, "save_purpose", writes.append)
    assert mark_embedding_ready(
        purpose="embedding", service_id="msvc_test", generation=state.generation,
        control_revision=state.control_revision, publish=lambda: callbacks.append(True),
    ) is False
    assert callbacks == []
    assert writes == []
    assert store.get_purpose("embedding") == stale


def test_catalog_publication_without_runtime_does_not_write(monkeypatch) -> None:
    before = get_catalog_index_store().get()
    writes = []
    monkeypatch.setattr(get_catalog_index_store(), "save", writes.append)
    monkeypatch.setattr(get_model_service_store(), "save_purpose", writes.append)
    assert get_embedding_runtime() is None
    assert publish_catalog_readiness(
        service_id="missing", generation=1, control_revision=1,
        counts=EmbeddingRefreshCounts(objects_written=1),
    ) is False
    assert writes == []
    assert get_catalog_index_store().get() == before


@pytest.mark.parametrize("purpose_fails", [False, True])
def test_catalog_publication_precedes_purpose_and_does_not_roll_back(
    monkeypatch, purpose_fails,
) -> None:
    _seed_embedding_runtime()
    store = get_model_service_store()
    state = store.get_purpose("embedding")
    index = get_catalog_index_store()
    index.save(replace(index.get(), rebuild_owed=True))
    events = []
    save_catalog = index.save
    save_purpose = store.save_purpose

    def catalog_save(value):
        assert store.get_purpose("embedding").ready is False
        events.append("catalog")
        return save_catalog(value)

    def purpose_save(value):
        assert index.get().ready is True
        assert index.get().rebuild_owed is False
        events.append("purpose")
        if purpose_fails:
            raise RuntimeError("purpose save failed")
        return save_purpose(value)

    monkeypatch.setattr(index, "save", catalog_save)
    monkeypatch.setattr(store, "save_purpose", purpose_save)
    kwargs = dict(
        service_id="msvc_test", generation=1, control_revision=state.control_revision,
        counts=EmbeddingRefreshCounts(
            objects_written=2, columns_written=3, objects_failed=4, columns_failed=5,
            objects_attempted=6, columns_attempted=8,
        ),
        progress="partial sweep", failure_summary="some rows failed",
    )
    if purpose_fails:
        with pytest.raises(RuntimeError, match="purpose save failed"):
            publish_catalog_readiness(**kwargs)
    else:
        assert publish_catalog_readiness(**kwargs) is True
    assert events == ["catalog", "purpose"]
    saved = index.get()
    assert saved.ready is True
    assert saved.generation_last_swept == 1
    assert (saved.objects_written, saved.columns_written) == (2, 3)
    assert (saved.objects_failed, saved.columns_failed) == (4, 5)
    assert (saved.objects_attempted, saved.columns_attempted) == (6, 8)
    assert saved.progress == "partial sweep"
    assert saved.failure_summary == "some rows failed"
    assert saved.rebuild_owed is False
    assert store.get_purpose("embedding").ready is (not purpose_fails)


@pytest.mark.parametrize("ready", [False, True])
@pytest.mark.parametrize("rebuild_owed", [False, True])
def test_failure_note_preserves_readiness_generation_and_rebuild_intent(
    ready, rebuild_owed,
) -> None:
    index = get_catalog_index_store()
    index.save(replace(index.get(), ready=ready, generation_last_swept=7,
                       rebuild_owed=rebuild_owed))
    saved = note_catalog_index_failure(
        failure_summary="deadline exceeded", objects_written=1, columns_written=2,
        objects_failed=3, columns_failed=4, objects_attempted=4, columns_attempted=6,
    )
    assert saved.ready is ready
    assert saved.generation_last_swept == 7
    assert saved.rebuild_owed is rebuild_owed
    assert (saved.objects_written, saved.columns_written) == (1, 2)
    assert (saved.objects_failed, saved.columns_failed) == (3, 4)
    assert (saved.objects_attempted, saved.columns_attempted) == (4, 6)
    assert saved.progress == saved.failure_summary == "deadline exceeded"


def test_runner_completes_job_only_after_both_readiness_writes(monkeypatch) -> None:
    _seed_embedding_runtime()
    store = get_model_service_store()
    original = store.save_purpose
    job = create_queued_job(kind="catalog_embed", input={})
    events = []

    def save_purpose(state):
        assert get_catalog_index_store().get().ready is True
        assert get_job_store().get(job.id).status == "running"
        events.append("purpose")
        return original(state)

    monkeypatch.setattr(store, "save_purpose", save_purpose)
    assert run_catalog_embed_job(job.id)["status"] == "succeeded"
    assert events == ["purpose"]
    assert get_job_store().get(job.id).status == "succeeded"


def test_runner_catalog_save_error_does_not_record_failure_note(monkeypatch) -> None:
    _seed_embedding_runtime()
    index = get_catalog_index_store()
    before = index.get()
    saves = []

    def fail_save(state):
        saves.append(state)
        raise RuntimeError("catalog save failed")

    monkeypatch.setattr(index, "save", fail_save)
    job = create_queued_job(kind="catalog_embed", input={})
    assert run_catalog_embed_job(job.id)["status"] == "failed"
    assert len(saves) == 1
    assert saves[0].ready is True
    assert index.get() == before
    assert get_model_service_store().get_purpose("embedding").ready is False
    assert get_job_store().get(job.id).error_summary == "catalog save failed"


@pytest.mark.parametrize("change", ["service", "generation", "revision", "missing"])
def test_catalog_stale_runtime_does_not_execute_publication(monkeypatch, change) -> None:
    _seed_embedding_runtime()
    runtime = get_embedding_runtime()
    assert runtime is not None
    store = get_model_service_store()
    state = store.get_purpose("embedding")
    if change == "missing":
        store.delete("msvc_test")
    else:
        field = {"service": "in_use_id", "generation": "generation",
                 "revision": "control_revision"}[change]
        store.save_purpose(replace(state, **{
            field: "other_service" if change == "service" else 99,
        }))
    writes = []
    monkeypatch.setattr(get_catalog_index_store(), "save", writes.append)
    monkeypatch.setattr(store, "save_purpose", writes.append)
    assert publish_catalog_readiness(
        service_id=runtime.service_id, generation=runtime.generation,
        control_revision=runtime.control_revision, counts=EmbeddingRefreshCounts(),
    ) is False
    assert writes == []
    assert get_catalog_index_store().get().ready is False
    assert store.get_purpose("embedding").ready is False


@pytest.mark.parametrize("repeat", [False, True])
def test_generation_restart_and_limit_keep_existing_outcomes(monkeypatch, repeat) -> None:
    _seed_embedding_runtime()
    _seed_source(object_count=1, columns_per_object=0)
    calls = []

    def refresh(source_id, *, progress, should_stop):
        calls.append(source_id)
        if repeat or len(calls) == 1:
            store = get_model_service_store()
            state = store.get_purpose("embedding")
            store.save_purpose(replace(state, generation=state.generation + 1))
            assert should_stop(EmbeddingRefreshCounts()) is True
        return EmbeddingRefreshCounts(objects_skipped=1)

    monkeypatch.setattr(
        "backend.metadata.catalog_embed_jobs.runner.refresh_source_embeddings", refresh,
    )
    job = create_queued_job(kind="catalog_embed", input={})
    assert run_catalog_embed_job(job.id)["status"] == "succeeded"
    record = get_job_store().get(job.id)
    if repeat:
        assert len(calls) == 9
        assert record.result["reason"] == "generation_changed"
        assert get_catalog_index_store().get().ready is False
        assert get_model_service_store().get_purpose("embedding").ready is False
    else:
        assert len(calls) == 2
        assert record.result["outcome"] == "completed"
        assert record.result["objects_skipped"] == 1
        assert get_catalog_index_store().get().generation_last_swept == 2
        assert get_catalog_index_store().get().ready is True


def test_timeout_equal_to_writes_still_publishes_catalog(monkeypatch) -> None:
    _seed_embedding_runtime()
    _seed_source(object_count=1, columns_per_object=0)

    def refresh(source_id, *, progress, should_stop):
        counts = EmbeddingRefreshCounts(
            objects_written=1, columns_failed=1, objects_attempted=1,
            columns_attempted=1, timeout_failed=1,
        )
        assert should_stop(counts) is False
        return counts

    monkeypatch.setattr(
        "backend.metadata.catalog_embed_jobs.runner.refresh_source_embeddings", refresh,
    )
    job = create_queued_job(kind="catalog_embed", input={})
    assert run_catalog_embed_job(job.id)["status"] == "succeeded"
    assert get_catalog_index_store().get().ready is True
    assert get_model_service_store().get_purpose("embedding").ready is True


def test_all_current_rows_skipped_can_publish_ready() -> None:
    _seed_embedding_runtime()
    _seed_source(object_count=1, columns_per_object=1)
    set_embed_fn_for_tests(lambda texts: [[1.0, 0.0] for _ in texts])
    try:
        first = create_queued_job(kind="catalog_embed", input={})
        assert run_catalog_embed_job(first.id)["status"] == "succeeded"
        index = get_catalog_index_store()
        index.save(replace(index.get(), ready=False, rebuild_owed=True))
        store = get_model_service_store()
        store.save_purpose(replace(store.get_purpose("embedding"), ready=False))
        second = create_queued_job(kind="catalog_embed", input={})
        assert run_catalog_embed_job(second.id)["status"] == "succeeded"
        result = get_job_store().get(second.id).result
        assert result["objects_written"] == result["columns_written"] == 0
        assert result["objects_skipped"] == result["columns_skipped"] == 1
        assert index.get().ready is True
        assert index.get().rebuild_owed is False
        assert store.get_purpose("embedding").ready is True
    finally:
        set_embed_fn_for_tests(None)


def test_control_revision_change_stops_the_sweep_before_ready() -> None:
    from dataclasses import replace

    from backend.admin.model_services.store import get_model_service_store

    _seed_source(object_count=8, columns_per_object=4)
    calls = {"n": 0}

    def embed(texts: list[str]) -> list[list[float]]:
        calls["n"] += 1
        if calls["n"] == 1:
            store = get_model_service_store()
            state = store.get_purpose("embedding")
            store.save_purpose(replace(state, control_revision=state.control_revision + 1))
        return [[1.0, 0.0] for _ in texts]

    record = _run_embed(embed_fn=embed)
    purpose = get_model_service_store().get_purpose("embedding")
    assert calls["n"] == 1
    assert purpose.ready is False
    assert purpose.generation == 1
    assert record.status == "succeeded"
    assert record.result is not None
    assert record.result["outcome"] == "skipped"
    assert record.result["reason"] == "aborted"


def test_catalog_embed_run_log_includes_planned_and_heartbeats() -> None:
    # 8 objects + 32 columns = 40 pending → two batches (32 then 8).
    _seed_source(object_count=8, columns_per_object=4)

    def ok(texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    record = _run_embed(embed_fn=ok)
    assert record.status == "succeeded"
    assert record.result is not None
    assert record.result["failure_reasons"] == []
    messages = _messages(record.id)
    assert "INFO indexing generation 1" in messages
    assert "INFO indexing embed-src…" in messages
    assert "INFO loading embed-src: 8 objects…" in messages
    assert "INFO loading embed-src: 8/8 objects" in messages
    assert "INFO indexing embed-src: 8 objects, 32 columns" in messages
    assert messages.index("INFO loading embed-src: 8 objects…") < messages.index(
        "INFO indexing embed-src: 8 objects, 32 columns"
    )
    assert "INFO embed-src 32/40 written=32 failed=0 skipped=0" in messages
    assert "INFO embed-src 40/40 written=40 failed=0 skipped=0" in messages
    assert "INFO finished embed-src: written 8 objects, 32 columns (failed 0/0)" in messages
    assert "INFO indexed 8 objects and 32 columns (failed 0/0)" in messages


def test_catalog_embed_loading_throttles_before_planned() -> None:
    listed = LOAD_EVERY + 6
    _seed_source(object_count=listed, columns_per_object=1)

    def ok(texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    record = _run_embed(embed_fn=ok)
    assert record.status == "succeeded"
    messages = _messages(record.id)
    start = f"INFO loading embed-src: {listed} objects…"
    mid = f"INFO loading embed-src: {LOAD_EVERY}/{listed} objects"
    done = f"INFO loading embed-src: {listed}/{listed} objects"
    planned = f"INFO indexing embed-src: {listed} objects, {listed} columns"
    assert start in messages
    assert mid in messages
    assert done in messages
    assert planned in messages
    assert messages.index(start) < messages.index(mid)
    assert messages.index(done) < messages.index(planned)


def test_real_embed_failure_omits_submitted_text_and_provider_body(
    monkeypatch,
    caplog,
) -> None:
    import io
    import logging
    import urllib.error

    from backend.admin.model_services import openai_compat

    _seed_source(object_count=1, columns_per_object=0)
    _seed_embedding_runtime()

    def _urlopen(_req: object, timeout: int = 0) -> object:
        raise urllib.error.HTTPError(
            "http://embed.test/v1/embeddings",
            400,
            "Bad Request",
            hdrs=None,
            fp=io.BytesIO(b"provider-secret-blob classified-phrase"),
        )

    monkeypatch.setattr(openai_compat.urllib.request, "urlopen", _urlopen)
    set_embed_fn_for_tests(None)
    job = create_queued_job(kind="catalog_embed", input={})
    try:
        with caplog.at_level(logging.WARNING):
            run_catalog_embed_job(job.id)
    finally:
        set_embed_fn_for_tests(None)
    record = get_job_store().get(job.id)
    assert record is not None
    assert record.status == "failed"
    visible = "\n".join(
        [caplog.text, record.error_summary or "", *_messages(record.id)]
    )
    assert "provider-secret-blob" not in visible
    assert "classified-phrase" not in visible
    assert "obj/postgresql/embed-src/public/table/t0" not in visible
    assert "http://embed.test/v1/embeddings" in visible


def test_repeated_embed_error_dedupes_and_fails_zero_writes() -> None:
    _seed_source(object_count=8, columns_per_object=4)
    reason = "Embeddings HTTP 400 at http://embed: bad"

    def boom(_texts: list[str]) -> list[list[float]]:
        raise RuntimeError(reason)

    record = _run_embed(embed_fn=boom)
    assert record.status == "failed"
    assert record.error_code == "JOB_EXECUTION_FAILED"
    assert record.error_summary is not None
    assert reason in record.error_summary
    messages = _messages(record.id)
    assert f"WARN embed failed ×32: {reason}" in messages
    assert f"WARN embed failed ×40: {reason}" in messages
    assert sum(1 for line in messages if line.startswith("WARN embed failed")) == 2


def test_partial_embed_failure_records_reason() -> None:
    # 40 pending items: first batch of 32 succeeds, tail batch of 8 fails.
    _seed_source(object_count=8, columns_per_object=4)
    calls = {"n": 0}

    def flaky(texts: list[str]) -> list[list[float]]:
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("column embed failed")
        return [[1.0, 0.0] for _ in texts]

    record = _run_embed(embed_fn=flaky)
    assert record.status == "succeeded"
    assert record.result is not None
    assert record.result["objects_written"] + record.result["columns_written"] == 32
    assert record.result["objects_failed"] + record.result["columns_failed"] == 8
    assert record.result["failure_reasons"] == [
        {"message": "column embed failed", "count": 8}
    ]
    messages = _messages(record.id)
    assert "WARN embed failed ×8: column embed failed" in messages
    assert any("last error: column embed failed (×8)" in line for line in messages)


def test_cancel_stops_at_batch_boundary() -> None:
    _seed_source(object_count=8, columns_per_object=4)
    calls = {"n": 0}
    _seed_embedding_runtime()
    job = create_queued_job(kind="catalog_embed", input={})

    def embed(texts: list[str]) -> list[list[float]]:
        calls["n"] += 1
        if calls["n"] == 1:
            mark_cancelled(job.id)
        return [[1.0, 0.0] for _ in texts]

    set_embed_fn_for_tests(embed)
    out = run_catalog_embed_job(job.id)
    set_embed_fn_for_tests(None)
    record = get_job_store().get(job.id)
    assert record is not None
    assert out["status"] == "cancelled"
    assert record.status == "cancelled"
    assert record.result is None
    assert calls["n"] == 1
    messages = _messages(job.id)
    assert "INFO embed-src 32/40 written=32 failed=0 skipped=0" in messages
    assert not any(line.startswith("INFO indexed ") for line in messages)
    assert not any(line.startswith("INFO finished embed-src") for line in messages)


def test_refresh_stops_at_first_load_heartbeat() -> None:
    from backend.metadata.catalog.index_embeddings import (
        LOAD_EVERY,
        refresh_source_embeddings,
    )
    from backend.metadata.catalog.store import get_catalog_store

    source_id = _seed_source(object_count=LOAD_EVERY + 6, columns_per_object=0)
    store = get_catalog_store()
    calls = {"n": 0}
    original = store.get_object

    def counting(object_id: str):
        calls["n"] += 1
        return original(object_id)

    store.get_object = counting  # type: ignore[method-assign]
    embed_calls = {"n": 0}

    def embed(texts: list[str]) -> list[list[float]]:
        embed_calls["n"] += 1
        return [[0.0] for _ in texts]

    set_embed_fn_for_tests(embed)
    try:
        counts = refresh_source_embeddings(
            source_id, should_stop=lambda _current: True
        )
    finally:
        store.get_object = original  # type: ignore[method-assign]
        set_embed_fn_for_tests(None)
    assert calls["n"] == LOAD_EVERY
    assert embed_calls["n"] == 0
    assert counts.written == 0


def test_cancel_during_load_releases_lock_without_writes() -> None:
    from backend.metadata.catalog.index_embeddings import LOAD_EVERY
    from backend.metadata.catalog.store import get_catalog_store
    from backend.metadata.source_job_runner.kind_locks import (
        try_acquire_named_execution_lock,
    )

    _seed_source(object_count=LOAD_EVERY + 4, columns_per_object=1)
    _seed_embedding_runtime()
    job = create_queued_job(kind="catalog_embed", input={})
    store = get_catalog_store()
    calls = {"n": 0}
    original = store.get_object

    def cancel_at_heartbeat(object_id: str):
        calls["n"] += 1
        if calls["n"] == LOAD_EVERY:
            mark_cancelled(job.id)
        return original(object_id)

    store.get_object = cancel_at_heartbeat  # type: ignore[method-assign]
    embed_calls = {"n": 0}

    def embed(texts: list[str]) -> list[list[float]]:
        embed_calls["n"] += 1
        return [[1.0, 0.0] for _ in texts]

    set_embed_fn_for_tests(embed)
    try:
        out = run_catalog_embed_job(job.id)
    finally:
        store.get_object = original  # type: ignore[method-assign]
        set_embed_fn_for_tests(None)
    record = get_job_store().get(job.id)
    assert record is not None
    assert out["status"] == "cancelled"
    assert record.status == "cancelled"
    assert record.result is None
    assert embed_calls["n"] == 0
    lock = try_acquire_named_execution_lock("catalog_embed")
    assert lock is not None
    lock.release()
