from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from backend.admin.errors import AuthForbidden
from backend.channel import channel_run, mirror_reads, runner, tasks
from backend.channel.nodes.spec import ERROR_OUTPUT, NodeResult
from backend.channel.routers import runs
from backend.channel.run_store import get_run_store
from backend.core.pagination import PageParams
from backend.core.errors import AppError
from backend.core.time import utc_now
from backend.jobs.routers import jobs
from backend.jobs.store import append_job_log, create_queued_job, get_job_store, mark_succeeded
import backend.main
from backend.tests.test_channel_recovery import _error_graph, _graph, _node, _publish, _republish, _run_published


MARKER = "synthetic-mirror-diagnostic"
SOURCE = "src_diagnostics"
ACTOR = "usr_author"
RECEIVER = "usr_receiver"


@pytest.fixture
def grants(monkeypatch):
    allowed = {ACTOR, RECEIVER}
    monkeypatch.setattr(mirror_reads, "get_user_store", lambda: SimpleNamespace(
        get_by_id=lambda user_id: SimpleNamespace(status="active", identity_source="local")))
    def authorize(*, execution_user_id, source_id, session=None):
        if execution_user_id not in allowed or source_id != SOURCE:
            raise mirror_reads.MirrorDataForbidden()
    monkeypatch.setattr(mirror_reads, "authorize_source_data", authorize)
    monkeypatch.setattr(channel_run, "authorize_graph", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "complete_mirror_success", lambda run, result:
                        mark_succeeded(run.job_id, result=result))
    return allowed


def _mirror_graph(*, error_channel_id=None, policy="stop"):
    graph = _graph("return {'ok': True}", limit=0, error_channel_id=error_channel_id)
    graph["nodes"][1]["on_error"] = policy
    graph["nodes"].append(_node("nd_mirror", "mirror", "read.mirror", {"object_id": "obj_diagnostics"}))
    return graph


def _node_result(monkeypatch, status):
    def finish(node, hooks):
        run = get_run_store().get_run(hooks.run_id)
        run.mirror_state = {**(run.mirror_state or {}), "source_ids": [SOURCE]}
        return NodeResult(status=status, error_code="MIRROR_READ_UNAVAILABLE",
                          error_message=MARKER, error_detail={"message": MARKER})

    original = channel_run.list_node_types
    monkeypatch.setattr(channel_run, "list_node_types", lambda: [
        replace(node, execute=finish, outputs=(*node.outputs, ERROR_OUTPUT))
        if node.type_id == "transform.code" else node
        for node in original()
    ])


@pytest.mark.parametrize(("status", "policy"), [("failed", "stop"), ("failed", "error_output"), ("skipped", "stop")])
def test_worker_stores_only_static_diagnostics(monkeypatch, grants, status, policy):
    _node_result(monkeypatch, status)
    channel = _publish("Mirror diagnostics", _mirror_graph(policy=policy))
    job_id = _run_published(channel)
    work = get_run_store().get_execution(job_id, 2)
    assert work.node_id == "nd_code"
    assert work.error_code == "MIRROR_READ_UNAVAILABLE"
    assert work.error_message and MARKER not in repr(work)
    assert work.error_detail is None
    job = get_job_store().get(job_id)
    if status == "skipped":
        assert work.output == {"skipped": True, "reason": "Mirror data is unavailable"}
    elif policy == "error_output":
        assert work.output == {"code": "MIRROR_READ_UNAVAILABLE", "message": "Mirror data is unavailable",
                               "detail": None}
    else:
        assert job.error_summary == "Mirror data is unavailable"
    assert MARKER not in repr(job)
    details = runs.http_get_run(channel.id, job_id, SimpleNamespace(id=ACTOR))
    assert MARKER not in repr(details)


def _job_view(job_id, user_id):
    return jobs.get_job(job_id, SimpleNamespace(id=user_id), SimpleNamespace(get_by_id=lambda _: None)).job


def test_legacy_diagnostics_are_projected_at_channel_and_job_endpoints(monkeypatch, grants):
    _node_result(monkeypatch, "failed")
    channel = _publish("Legacy diagnostics", _mirror_graph())
    job_id = _run_published(channel)
    run = get_run_store().get_run(job_id)
    run.context.pop("diagnostics_version", None)
    job = get_job_store().get(job_id)
    job.error_summary = MARKER
    append_job_log(job_id, level="error", message=MARKER)
    work = get_run_store().get_execution(job_id, 2)
    get_run_store().finish_execution(replace(work, error_message=MARKER, error_detail={"note": MARKER},
                                               output={"reason": MARKER}))

    actor = SimpleNamespace(id=ACTOR)
    assert MARKER not in repr(runs.http_get_run(channel.id, job_id, actor))
    items = runs.http_list_executions(channel.id, job_id, actor, round_index=None,
                                     page=PageParams(limit=10, offset=0))["items"]
    assert MARKER not in repr(items)
    assert next(item for item in items if item["seq"] == 2)["error_code"] == "MIRROR_READ_UNAVAILABLE"
    with pytest.raises(AppError, match="AUTH_FORBIDDEN"):
        runs.http_execution_output(channel.id, job_id, 2, actor, limit=10, offset=0)
    assert MARKER not in repr(_job_view(job_id, ACTOR))
    assert MARKER not in jobs.get_job_logs(job_id, actor).body


def test_retained_job_hides_legacy_diagnostics_after_run_purge(monkeypatch, grants):
    _node_result(monkeypatch, "failed")
    channel = _publish("Retained Job diagnostics", _mirror_graph())
    job_id = _run_published(channel)
    job = get_job_store().get(job_id)
    get_job_store().save(replace(job, error_summary=MARKER))
    append_job_log(job_id, level="error", message=MARKER)

    assert get_run_store().delete_expired_terminal_runs(utc_now() + timedelta(seconds=1)) == 1

    public = _job_view(job_id, ACTOR)
    assert public.status == "failed"
    assert public.input == {}
    assert public.error_message == "Mirror data is unavailable"
    assert jobs.get_job_logs(job_id, SimpleNamespace(id=ACTOR)).body == "Mirror data is unavailable"


def test_worker_preserves_legacy_payload_restrictions_when_old_records_exist(monkeypatch, grants):
    _node_result(monkeypatch, "failed")
    channel = _publish("Retained execution", _mirror_graph())
    job, _run = channel_run.mint_on_demand_run(
        channel_id=channel.id, channel_name=channel.name, target="published", ignore_checkpoints=False,
        actor_id=ACTOR, trigger_node_id="nd_trigger", version=None, draft_revision=None,
        graph=None, stop_at_node_id=None,
    )
    store = get_run_store()
    old = store.start_execution(job.id, "nd_code")
    store.finish_execution(replace(old, status="skipped", output={"skipped": True, "reason": MARKER}))

    assert runner.run_channel_job(job.id) == {"status": "failed"}
    actor = SimpleNamespace(id=ACTOR)
    with pytest.raises(AppError, match="AUTH_FORBIDDEN"):
        runs.http_execution_output(channel.id, job.id, old.seq, actor, limit=10, offset=0)


@pytest.mark.parametrize("viewer_has_source_membership", [False, True])
def test_error_workflow_inherits_sources_and_rechecks_both_identities(
    monkeypatch, grants, viewer_has_source_membership,
):
    _node_result(monkeypatch, "failed")
    graph = _error_graph()
    graph["settings"]["mirror_execution_user_id"] = RECEIVER
    child = _publish("Receiver", graph)
    parent = _publish("Mirror producer", _mirror_graph(error_channel_id=child.id))
    queued = []
    monkeypatch.setattr(channel_run, "dispatch", queued.append)
    grants.remove(RECEIVER)
    _run_published(parent)
    assert queued == []

    grants.add(RECEIVER)
    parent_id = _run_published(parent)
    assert len(queued) == 1
    job_id = queued[0]
    child_run = get_run_store().get_run(job_id)
    assert child_run.mirror_execution_user_id == RECEIVER
    assert child_run.mirror_state["source_ids"] == [SOURCE]
    assert _job_view(job_id, RECEIVER).input["error_source"]["job_id"] == parent_id
    assert MARKER not in repr(_job_view(job_id, RECEIVER))
    retry, retry_run = _retry(child, child_run)
    assert retry_run.mirror_execution_user_id == RECEIVER
    assert retry_run.mirror_state["source_ids"] == [SOURCE]
    assert _job_view(retry.id, RECEIVER).input["error_source"]["job_id"] == parent_id
    grants.remove(ACTOR)
    if viewer_has_source_membership:
        original_authorize = mirror_reads.authorize_source_data

        def authorize(*, execution_user_id, source_id, session=None):
            if execution_user_id == ACTOR:
                raise AuthForbidden()
            return original_authorize(execution_user_id=execution_user_id, source_id=source_id)

        monkeypatch.setattr(mirror_reads, "authorize_source_data", authorize)
    assert "error_source" not in _job_view(job_id, ACTOR).input
    assert "error_source" not in _job_view(retry.id, ACTOR).input

    assert runner.run_channel_job(job_id) == {"status": "succeeded"}
    assert get_run_store().get_execution(job_id, 1).output["job_id"] == parent_id
    grants.remove(RECEIVER)
    assert runner.run_channel_job(retry.id) == {"status": "failed"}
    assert get_job_store().get(retry.id).error_code == "AUTH_FORBIDDEN"
    assert get_run_store().get_execution(retry.id, 1) is None
    with pytest.raises(AppError, match="AUTH_FORBIDDEN"):
        runs.http_list_executions(child.id, job_id, SimpleNamespace(id=RECEIVER),
                                  round_index=None, page=PageParams(limit=10, offset=0))

    grants.update({ACTOR, RECEIVER})
    _run_published(parent)
    grants.remove(RECEIVER)
    assert runner.run_channel_job(queued[-1]) == {"status": "failed"}
    assert get_job_store().get(queued[-1]).error_code == "AUTH_FORBIDDEN"
    assert get_run_store().get_execution(queued[-1], 1) is None


def _retry(channel, parent):
    return channel_run.mint_followup_run(
        channel_id=channel.id, channel_name=channel.name, trigger_kind="retry", trigger_ref=parent.job_id,
        trigger_node=parent.trigger_node_id, version=parent.version,
        job_input={"channel_id": channel.id, "target": "published", "pin_version": True,
                   "version": parent.version, "retry_of_job_id": parent.job_id},
    )


def _error_input(parent):
    return {"error_source": {
        "channel_id": parent.channel_id, "channel_name": "Sender", "job_id": parent.job_id,
        "version": parent.version, "attempt": 1,
        "error": {"code": "CHANNEL_NODE_FAILED", "message": MARKER, "node_id": "nd_code"},
        "triggered_by": None, "triggered_at": "2026-01-01T00:00:00Z",
    }}


def _mint_error(channel, parent):
    return channel_run.mint_followup_run(
        channel_id=channel.id, channel_name=channel.name, trigger_kind="error", trigger_ref=parent.job_id,
        trigger_node="nd_error", version=None,
        job_input={"channel_id": channel.id, "target": "published", **_error_input(parent)},
    )


def test_unknown_protected_parent_cannot_mint_followups(grants):
    sender = _publish("Sender", _graph("raise ValueError('failure')", limit=0, error_channel_id=None))
    parent = get_run_store().get_run(_run_published(sender))
    parent.mirror_state = {"inherited_source_ids": [SOURCE]}
    receiver = _publish("Receiver", _error_graph())

    with pytest.raises(AppError, match="AUTH_FORBIDDEN"):
        _retry(sender, parent)
    with pytest.raises(AppError, match="AUTH_FORBIDDEN"):
        _mint_error(receiver, parent)


@pytest.mark.parametrize("legacy", [False, True])
def test_mirror_receiver_never_executes_raw_error_input_from_ordinary_sender(grants, legacy):
    sender = _publish("Sender", _graph("raise ValueError('failure')", limit=0, error_channel_id=None))
    parent = get_run_store().get_run(_run_published(sender))
    graph = _error_graph()
    graph["settings"]["mirror_execution_user_id"] = RECEIVER
    graph["nodes"].append(_node("nd_mirror", "mirror", "read.mirror", {"object_id": "obj_diagnostics"}))
    receiver = _publish("Receiver", graph)
    job, record = _mint_error(receiver, parent)
    if legacy:
        job.input = {"channel_id": receiver.id, **_error_input(parent)}
        record.mirror_state = {"source_ids": [SOURCE]}
        assert runner.run_channel_job(job.id) == {"status": "failed"}
        assert get_job_store().get(job.id).error_code == "AUTH_FORBIDDEN"
        assert get_run_store().get_execution(job.id, 1) is None
    else:
        assert job.input["error_source"]["error"]["message"] == "Channel node failed"
        record.mirror_state = {"source_ids": [SOURCE]}
        assert runner.run_channel_job(job.id) == {"status": "succeeded"}
        assert MARKER not in repr(get_run_store().get_execution(job.id, 1))


def test_inherited_only_worker_requires_persisted_sources(grants):
    sender = _publish("Sender", _graph("raise ValueError('failure')", limit=0, error_channel_id=None))
    parent = get_run_store().get_run(_run_published(sender))
    parent.mirror_state = {"source_ids": [SOURCE]}
    graph = _error_graph()
    graph["settings"]["mirror_execution_user_id"] = RECEIVER
    receiver = _publish("Receiver", graph)
    job, record = _mint_error(receiver, parent)
    record.mirror_state = None

    assert runner.run_channel_job(job.id) == {"status": "failed"}
    assert get_job_store().get(job.id).error_code == "AUTH_FORBIDDEN"
    assert get_run_store().get_execution(job.id, 1) is None


def test_error_workflow_republished_with_mirror_requires_admitted_identity(grants):
    sender = _publish("Sender", _graph("raise ValueError('failure')", limit=0, error_channel_id=None))
    parent = get_run_store().get_run(_run_published(sender))
    receiver = _publish("Receiver", _error_graph())
    job, record = _mint_error(receiver, parent)
    assert record.mirror_execution_user_id is None

    graph = _error_graph()
    graph["settings"]["mirror_execution_user_id"] = RECEIVER
    graph["nodes"].append(_node("nd_mirror", "mirror", "read.mirror", {"object_id": "obj_diagnostics"}))
    _republish(receiver.id, graph)

    assert runner.run_channel_job(job.id) == {"status": "failed"}
    assert get_job_store().get(job.id).error_code == "AUTH_FORBIDDEN"
    assert get_run_store().get_execution(job.id, 1) is None


def test_unknown_or_legacy_inherited_payload_does_not_reach_trigger(grants):
    child = _publish("Receiver", _error_graph())
    job = create_queued_job(kind="channel_run", input={"channel_id": child.id, "error_source": {
        "job_id": "missing", "error": {"message": MARKER},
    }}, trigger_kind="error", trigger_ref="missing")
    record = channel_run.ChannelRunRecord(
        job_id=job.id, channel_id=child.id, target="published", version=None, draft_revision=None,
        graph=_error_graph(), trigger_node_id="nd_error", ignore_checkpoints=False, outcome=None,
        failed_node_id=None, skipped_node_ids=[], created_at=job.created_at,
    )
    get_run_store().insert_run(record)
    assert "error_source" not in _job_view(job.id, RECEIVER).input
    with pytest.raises(AppError, match="AUTH_FORBIDDEN"):
        _retry(child, record)
    assert runner.run_channel_job(job.id) == {"status": "failed"}
    assert get_run_store().get_execution(job.id, 1) is None


def test_supervision_emits_static_log_when_mirror_run_fails(monkeypatch, grants, caplog):
    channel = _publish("Mirror supervision", _mirror_graph())
    job, _run = channel_run.mint_on_demand_run(
        channel_id=channel.id, channel_name=channel.name, target="published", ignore_checkpoints=False,
        actor_id=ACTOR, trigger_node_id="nd_trigger", version=None, draft_revision=None,
        graph=None, stop_at_node_id=None,
    )

    def fail(*args, **kwargs):
        raise RuntimeError(MARKER)

    monkeypatch.setattr(tasks, "supervise", fail)
    assert tasks.run_job(job.id) == {"status": "failed"}
    assert MARKER not in caplog.text
    assert MARKER not in repr(get_job_store().get(job.id))
