"""Job observation presentation: records in, JobOut out."""

from __future__ import annotations

from dataclasses import dataclass

from backend.core.time import utc_now
from backend.jobs.api import present_jobs
from backend.jobs.store import JobRecord


@dataclass
class _User:
    display_name: str


class _Users:
    def __init__(self, by_id: dict[str, _User]) -> None:
        self._by_id = by_id

    def get_by_id(self, user_id: str) -> _User | None:
        return self._by_id.get(user_id)


@dataclass
class _Schedule:
    name: str


class _Schedules:
    def __init__(self, by_id: dict[str, _Schedule]) -> None:
        self._by_id = by_id

    def get_by_id(self, schedule_id: str) -> _Schedule | None:
        return self._by_id.get(schedule_id)


def _record(
    *,
    id: str,
    trigger_kind: str | None,
    trigger_ref: str | None,
) -> JobRecord:
    now = utc_now()
    return JobRecord(
        id=id,
        kind="structure",
        status="queued",
        input={"source_id": "src_1"},
        result=None,
        created_by=None,
        celery_task_id=None,
        error_code=None,
        error_summary=None,
        summary="structure · demo",
        trigger_kind=trigger_kind,
        trigger_ref=trigger_ref,
        log_body="",
        log_updated_at=None,
        scheduled_for=None,
        claimed_by=None,
        locked_at=None,
        created_at=now,
        started_at=None,
        finished_at=None,
    )


def test_present_jobs_resolves_user_and_schedule_names() -> None:
    users = _Users({"user_1": _User(display_name="Ada")})
    schedules = _Schedules(
        {
            "sched_1": _Schedule(name="structure · demo"),
            "sched_blank": _Schedule(name="  "),
        }
    )
    user_job = _record(id="job_user", trigger_kind="user", trigger_ref="user_1")
    orphan_user = _record(
        id="job_orphan_user", trigger_kind="user", trigger_ref="user_missing"
    )
    schedule_job = _record(
        id="job_sched", trigger_kind="schedule", trigger_ref="sched_1"
    )
    orphan_schedule = _record(
        id="job_orphan_sched", trigger_kind="schedule", trigger_ref="sched_gone"
    )
    blank_schedule = _record(
        id="job_blank_sched", trigger_kind="schedule", trigger_ref="sched_blank"
    )

    outs = present_jobs(
        [user_job, orphan_user, schedule_job, orphan_schedule, blank_schedule],
        users=users,
        schedules=schedules,
    )
    by_id = {item.id: item for item in outs}

    assert by_id["job_user"].trigger_actor_name == "Ada"
    assert by_id["job_user"].trigger_schedule_name is None
    assert by_id["job_orphan_user"].trigger_actor_name is None
    assert by_id["job_sched"].trigger_schedule_name == "structure · demo"
    assert by_id["job_sched"].trigger_actor_name is None
    assert by_id["job_orphan_sched"].trigger_schedule_name is None
    assert by_id["job_blank_sched"].trigger_schedule_name is None
