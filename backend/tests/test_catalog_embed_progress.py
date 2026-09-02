"""catalog_embed run-log progress, deduplicated failures, and cooperative cancel."""

from __future__ import annotations

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
from backend.metadata.catalog_embed_jobs.runner import run_catalog_embed_job
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
        "INFO embed-src 256/300 written=256 failed=0 skipped=0",
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
        "INFO loading embed-src: 64/200 objects"
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
                business_domain_id=None,
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
        fail_safe_threshold=1.0,
    )
    return source_id


def _run_embed(*, embed_fn) -> object:
    set_embed_fn_for_tests(embed_fn)
    job = create_queued_job(
        kind="catalog_embed",
        input={"model_service_id": "msvc_test", "generation": 1},
    )
    run_catalog_embed_job(job.id)
    record = get_job_store().get(job.id)
    assert record is not None
    set_embed_fn_for_tests(None)
    return record


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
    _seed_source(object_count=70, columns_per_object=1)

    def ok(texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    record = _run_embed(embed_fn=ok)
    assert record.status == "succeeded"
    messages = _messages(record.id)
    assert "INFO loading embed-src: 70 objects…" in messages
    assert "INFO loading embed-src: 64/70 objects" in messages
    assert "INFO loading embed-src: 70/70 objects" in messages
    assert "INFO indexing embed-src: 70 objects, 70 columns" in messages
    assert messages.index("INFO loading embed-src: 70 objects…") < messages.index(
        "INFO loading embed-src: 64/70 objects"
    )
    assert messages.index("INFO loading embed-src: 70/70 objects") < messages.index(
        "INFO indexing embed-src: 70 objects, 70 columns"
    )


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
    job = create_queued_job(
        kind="catalog_embed",
        input={"model_service_id": "msvc_test", "generation": 1},
    )

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
