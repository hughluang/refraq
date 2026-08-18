"""Structure collect run-log progress (schema-scoped fetch phases)."""

from __future__ import annotations

import os

import pytest

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.jobs.store import create_queued_job, get_job_store  # noqa: E402
from backend.metadata.connectors.base import (  # noqa: E402
    CollectedColumn,
    CollectedObject,
    CollectedStructure,
)
from backend.metadata.structure_jobs.collect_log import StructureCollectLog  # noqa: E402
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


def test_listed_zero_skips_fetch_lines() -> None:
    job = create_queued_job(kind="structure", input={"source_id": "s1"})
    log = StructureCollectLog(job.id)
    log.listing_objects("public")
    log.listed_objects(0)
    assert _messages(job.id) == [
        "INFO listing objects in public…",
        "INFO listed 0 objects",
    ]


def test_fetch_phases_are_fixed_lines() -> None:
    job = create_queued_job(kind="structure", input={"source_id": "s1"})
    log = StructureCollectLog(job.id)
    log.listing_objects("dbo")
    log.listed_objects(2)
    log.fetched("columns", 5)
    log.fetched("primary_keys", 2)
    log.fetched("foreign_keys", 0)
    log.fetched("indexes", 1)
    log.fetched("definitions", 0)
    log.assembled(2)
    assert _messages(job.id) == [
        "INFO listing objects in dbo…",
        "INFO listed 2 objects",
        "INFO read 5 columns",
        "INFO read 2 primary key columns",
        "INFO read 0 foreign key columns",
        "INFO read 1 index columns",
        "INFO read 0 view definitions",
        "INFO assembled 2 objects",
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
            progress.fetched("columns", 2)
            progress.fetched("primary_keys", 2)
            progress.fetched("foreign_keys", 0)
            progress.fetched("indexes", 0)
            progress.fetched("definitions", 0)
            progress.assembled(len(objects))
        return CollectedStructure(objects=objects)


def test_structure_job_run_log_includes_fetch_phases(
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
    assert "INFO read 2 columns" in messages
    assert "INFO assembled 2 objects" in messages
    assert "INFO collected 2 objects, 2 columns" in messages
    assert messages.index("INFO listed 2 objects") < messages.index(
        "INFO assembled 2 objects"
    )
