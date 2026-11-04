"""Run history predicates apply to the retained run/Job pair before paging."""

from datetime import timedelta

from backend.channel.run_store import ChannelRunRecord, get_run_store
from backend.core.time import utc_now
from backend.jobs.store import create_queued_job, get_job_store, mark_failed


def test_history_status_and_target_before_pagination():
    runs = get_run_store()
    now = utc_now()
    expected = []
    for index in range(55):
        job = create_queued_job(
            kind="channel_run", input={}, created_at=now + timedelta(seconds=index)
        )
        target = "draft" if index == 1 else "published"
        runs.insert_run(ChannelRunRecord(
            job_id=job.id, channel_id="history", target=target,
            version=None, draft_revision=None, graph=None, trigger_node_id="start",
            ignore_checkpoints=False, outcome=None, failed_node_id=None,
            skipped_node_ids=[], created_at=job.created_at,
        ))
        if index < 3:
            mark_failed(job.id, error_code="CHANNEL_NODE_FAILED", error_summary="Failed")
            if target == "published":
                expected.insert(0, job.id)
    first, total = runs.list_runs("history", status="failed", target="published", limit=1, offset=0)
    assert total == 2
    assert [run.job_id for run in first] == expected[:1]
    second, total = runs.list_runs("history", status="failed", target="published", limit=1, offset=1)
    assert total == 2
    assert [run.job_id for run in second] == expected[1:]
    empty, total = runs.list_runs("history", status="failed", target="published", limit=1, offset=2)
    assert empty == []
    assert total == 2
    get_job_store().delete(expected[0])
    remaining, total = runs.list_runs("history", status="failed", target="published", limit=50, offset=0)
    assert [run.job_id for run in remaining] == expected[1:]
    assert total == 1
    _, total = runs.list_runs("history", status=None, target=None, limit=50, offset=0)
    assert total == 54
    invalid, total = runs.list_runs("history", status="not-a-status", target=None, limit=50, offset=0)
    assert invalid == []
    assert total == 0
