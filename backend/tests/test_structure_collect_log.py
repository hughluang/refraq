"""Structure collect run-log progress (listed + throttled objects {done}/{total})."""

from __future__ import annotations

import os
from datetime import timedelta

import pytest

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.core.time import FixedClock, parse_instant, set_clock  # noqa: E402
from backend.jobs.store import create_queued_job, get_job_store  # noqa: E402
from backend.metadata.connectors.base import (  # noqa: E402
    CollectedColumn,
    CollectedObject,
    CollectedStructure,
)
from backend.metadata.structure_jobs.collect_log import (  # noqa: E402
    OBJECT_PROGRESS_EVERY,
    OBJECT_PROGRESS_INTERVAL,
    StructureCollectLog,
)
from backend.metadata.structure_jobs.service import run_structure_job  # noqa: E402
from backend.metadata.sources.service import create_source  # noqa: E402


def _messages(job_id: str) -> list[str]:
    stored = get_job_store().get(job_id)
    assert stored is not None
    out: list[str] = []
    for line in stored.log_body.splitlines():
        parts = line.split(" ", 2)
        assert len(parts) == 3
        out.append(f"{parts[1]} {parts[2]}")
    return out


def _object_lines(messages: list[str]) -> list[str]:
    return [m for m in messages if m.startswith("INFO objects ")]


def test_listed_zero_skips_object_counts() -> None:
    job = create_queued_job(kind="structure", input={"source_id": "s1"})
    log = StructureCollectLog(job.id)
    log.listing_objects("public")
    log.listed_objects(0)
    assert _messages(job.id) == [
        "INFO listing objects in public…",
        "INFO listed 0 objects",
    ]


def test_count_throttle_and_terminal() -> None:
    job = create_queued_job(kind="structure", input={"source_id": "s1"})
    log = StructureCollectLog(job.id)
    total = OBJECT_PROGRESS_EVERY + 5
    log.listed_objects(total)
    for done in range(1, total + 1):
        log.object_done(done, total)
    assert _object_lines(_messages(job.id)) == [
        f"INFO objects 0/{total}",
        f"INFO objects {OBJECT_PROGRESS_EVERY}/{total}",
        f"INFO objects {total}/{total}",
    ]


def test_time_throttle_emits_between_count_marks() -> None:
    clock = FixedClock(parse_instant("2026-08-15T03:14:41Z"))
    set_clock(clock)
    job = create_queued_job(kind="structure", input={"source_id": "s1"})
    log = StructureCollectLog(job.id)
    log.listed_objects(8)
    log.object_done(1, 8)
    clock.advance(OBJECT_PROGRESS_INTERVAL)
    log.object_done(2, 8)
    log.object_done(3, 8)
    clock.advance(timedelta(seconds=1))
    log.object_done(8, 8)
    assert _object_lines(_messages(job.id)) == [
        "INFO objects 0/8",
        "INFO objects 2/8",
        "INFO objects 8/8",
    ]


def test_terminal_line_is_not_duplicated() -> None:
    job = create_queued_job(kind="structure", input={"source_id": "s1"})
    log = StructureCollectLog(job.id)
    log.listed_objects(OBJECT_PROGRESS_EVERY)
    for done in range(1, OBJECT_PROGRESS_EVERY + 1):
        log.object_done(done, OBJECT_PROGRESS_EVERY)
    log.object_done(OBJECT_PROGRESS_EVERY, OBJECT_PROGRESS_EVERY)
    assert _object_lines(_messages(job.id)) == [
        f"INFO objects 0/{OBJECT_PROGRESS_EVERY}",
        f"INFO objects {OBJECT_PROGRESS_EVERY}/{OBJECT_PROGRESS_EVERY}",
    ]


class _ProgressConnector:
    engine = "postgresql"

    def collect_structure(self, endpoint, progress=None) -> CollectedStructure:  # noqa: ANN001
        objects = [
            CollectedObject(
                schema_name="public",
                name="alpha",
                object_type="table",
                columns=[
                    CollectedColumn(
                        name="id", ordinal=1, data_type="integer", nullable=False
                    )
                ],
                primary_key=["id"],
            ),
            CollectedObject(
                schema_name="public",
                name="beta",
                object_type="table",
                columns=[
                    CollectedColumn(
                        name="id", ordinal=1, data_type="integer", nullable=False
                    )
                ],
                primary_key=["id"],
            ),
        ]
        if progress is not None:
            progress.listing_objects(endpoint.schema_filter)
            progress.listed_objects(len(objects))
            for index, _obj in enumerate(objects, start=1):
                progress.object_done(index, len(objects))
        return CollectedStructure(objects=objects)


def test_structure_job_run_log_includes_object_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.metadata.connectors.runtime.get_connector",
        lambda engine: _ProgressConnector(),
    )
    source = create_source(
        key="log-src",
        name="Log",
        kind="database",
        description=None,
        engine="postgresql",
        access={
            "host": "127.0.0.1",
            "port": 5432,
            "username": "u",
            "password": "p",
            "ssl_mode": "require",
            "database": "MES",
            "schema": "public",
            "extra": {},
        },
    )
    job = create_queued_job(kind="structure", input={"source_id": source.id})
    out = run_structure_job(job.id)
    assert out["status"] == "succeeded"
    messages = _messages(job.id)
    assert "INFO collecting structure…" in messages
    assert "INFO listing objects in public…" in messages
    assert "INFO listed 2 objects" in messages
    assert "INFO objects 0/2" in messages
    assert "INFO objects 2/2" in messages
    assert "INFO collected 2 objects, 2 columns" in messages
    assert messages.index("INFO objects 0/2") < messages.index("INFO objects 2/2")
